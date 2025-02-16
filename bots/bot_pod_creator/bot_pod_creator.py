from kubernetes import client, config
from typing import Optional, Dict, List
import uuid
import os

class BotPodCreator:
    def __init__(self, namespace: str = "attendee"):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        
        self.v1 = client.CoreV1Api()
        self.namespace = namespace
        
        # Get configuration from environment variables
        self.app_name = os.getenv('CUBER_APP_NAME', 'attendee')
        self.app_version = os.getenv('CUBER_RELEASE_VERSION')
        
        if not self.app_version:
            raise ValueError("CUBER_RELEASE_VERSION environment variable is required")
            
        # Parse instance from version (matches your pattern of {hash}-{timestamp})
        self.app_instance = f"{self.app_name}-{self.app_version.split('-')[-1]}"
        self.image = f"nduncan{self.app_name}/{self.app_name}:{self.app_version}"

    def create_bot_pod(
        self,
        bot_id: int,
        bot_name: Optional[str] = None,
    ) -> Dict:
        """
        Create a bot pod with configuration from environment.
        
        Args:
            bot_id: Integer ID of the bot to run
            bot_name: Optional name for the bot (will generate if not provided)
        """
        if bot_name is None:
            bot_name = f"bot-{bot_id}-{uuid.uuid4().hex[:8]}"

        # Set the command based on bot_id
        # python manage.py run_bot --botid
        command = ["python", "manage.py", "run_bot", "--botid", str(bot_id)]

        # Metadata labels matching the deployment
        labels = {
            "app.kubernetes.io/name": self.app_name,
            "app.kubernetes.io/instance": self.app_instance,
            "app.kubernetes.io/version": self.app_version,
            "app.kubernetes.io/managed-by": "cuber",
            "app": "bot-proc"
        }

        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=bot_name,
                namespace=self.namespace,
                labels=labels
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="bot-proc",
                        image=self.image,
                        image_pull_policy="Always",
                        command=command,
                        resources=client.V1ResourceRequirements(
                            requests={
                                "cpu": "4",
                                "memory": "4Gi"
                            },
                            limits={
                                "memory": "4Gi"
                            }
                        ),
                        env_from=[
                            client.V1EnvFromSource(
                                config_map_ref=client.V1ConfigMapEnvSource(
                                    name="env"
                                )
                            ),
                            client.V1EnvFromSource(
                                secret_ref=client.V1SecretEnvSource(
                                    name="app-secrets"
                                )
                            )
                        ],
                        env=[]
                    )
                ],
                restart_policy="Never",
                image_pull_secrets=[
                    client.V1LocalObjectReference(
                        name="regcred"
                    )
                ],
                termination_grace_period_seconds=60
            )
        )

        try:
            api_response = self.v1.create_namespaced_pod(
                namespace=self.namespace,
                body=pod
            )
            
            return {
                "name": api_response.metadata.name,
                "status": api_response.status.phase,
                "created": True,
                "image": self.image,
                "app_instance": self.app_instance,
                "app_version": self.app_version
            }
            
        except client.ApiException as e:
            return {
                "name": bot_name,
                "status": "Error",
                "created": False,
                "error": str(e)
            }

    def delete_bot_pod(self, pod_name: str) -> Dict:
        try:
            self.v1.delete_namespaced_pod(
                name=pod_name,
                namespace=self.namespace,
                grace_period_seconds=60
            )
            return {"deleted": True}
        except client.ApiException as e:
            return {
                "deleted": False,
                "error": str(e)
            }