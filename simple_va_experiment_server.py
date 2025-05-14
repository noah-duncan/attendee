import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebRTC-Signaling")

connected_clients = {}
senders = []
receivers = []

async def handle_connection(websocket, path):
    client_id = None
    try:
        async for message in websocket:
            data = json.loads(message)
            logger.info(f"Received message: {data['type']} from {data.get('clientId', 'unknown')}")
            
            if data['type'] == 'register':
                client_id = data['clientId']
                connected_clients[client_id] = websocket
                
                if client_id.startswith('sender'):
                    senders.append(client_id)
                    logger.info(f"Sender registered: {client_id}")
                    
                    # Notify sender about any existing receivers
                    if receivers:
                        await websocket.send(json.dumps({
                            'type': 'receiver-ready',
                            'receiverId': receivers[0]  # Just use the first receiver for simplicity
                        }))
                
                elif client_id.startswith('receiver'):
                    receivers.append(client_id)
                    logger.info(f"Receiver registered: {client_id}")
                    
                    # Notify all senders about new receiver
                    for sender_id in senders:
                        if sender_id in connected_clients:
                            await connected_clients[sender_id].send(json.dumps({
                                'type': 'receiver-ready',
                                'receiverId': client_id
                            }))
            
            elif data['type'] == 'offer':
                target_id = data['targetId']
                if target_id in connected_clients:
                    logger.info(f"Forwarding offer from {client_id} to {target_id}")
                    await connected_clients[target_id].send(json.dumps({
                        'type': 'offer',
                        'senderId': client_id,
                        'offer': data['offer']
                    }))
                else:
                    logger.warning(f"Target client {target_id} not found")
                    
            elif data['type'] == 'answer':
                target_id = data['targetId']
                if target_id in connected_clients:
                    logger.info(f"Forwarding answer from {client_id} to {target_id}")
                    await connected_clients[target_id].send(json.dumps({
                        'type': 'answer',
                        'senderId': client_id,
                        'answer': data['answer']
                    }))
                    
            elif data['type'] == 'ice-candidate':
                target_id = data['targetId']
                if target_id in connected_clients:
                    logger.info(f"Forwarding ICE candidate from {client_id} to {target_id}")
                    await connected_clients[target_id].send(json.dumps({
                        'type': 'ice-candidate',
                        'senderId': client_id,
                        'candidate': data['candidate']
                    }))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if client_id:
            if client_id in connected_clients:
                del connected_clients[client_id]
            if client_id in senders:
                senders.remove(client_id)
            if client_id in receivers:
                receivers.remove(client_id)
            logger.info(f"Client disconnected: {client_id}")

async def main():
    server = await websockets.serve(handle_connection, "localhost", 8765)
    logger.info("Signaling server running on ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())