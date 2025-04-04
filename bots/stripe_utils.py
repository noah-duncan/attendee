import logging

from django.http import HttpResponse

from accounts.models import Organization, User

from .models import CreditTransaction, CreditTransactionManager

logger = logging.getLogger(__name__)


def process_checkout_session_completed(checkout_session):
    # Get the organization ID from the metadata
    organization_id = checkout_session.metadata.get("organization_id")
    organization = Organization.objects.get(id=organization_id)
    if not organization:
        return HttpResponse("Invalid organization ID", status=400)

    user_id = checkout_session.metadata.get("user_id")
    user = User.objects.get(id=user_id)
    if not user:
        return HttpResponse("Invalid user ID", status=400)

    if user.organization != organization:
        return HttpResponse("User does not belong to organization", status=400)

    # Get the credit amount from the metadata
    credit_amount = checkout_session.metadata.get("credit_amount")
    if not credit_amount:
        return HttpResponse("No credit amount provided", status=400)

    try:
        centicredits_delta = int(credit_amount) * 100
    except ValueError:
        return HttpResponse("Invalid credit amount format", status=400)

    if CreditTransaction.objects.filter(stripe_payment_intent_id=checkout_session.payment_intent).exists():
        logger.info(f"Payment intent {checkout_session.payment_intent} already processed")
        return HttpResponse(f"Payment intent {checkout_session.payment_intent} already processed", status=200)

    try:
        # Get payment amount in USD from checkout session (amount_total is in cents)
        amount_usd = checkout_session.amount_total / 100

        CreditTransactionManager.create_transaction(
            organization=organization,
            centicredits_delta=centicredits_delta,
            bot=None,
            stripe_payment_intent_id=checkout_session.payment_intent,
            description=f"Stripe payment of ${amount_usd:.2f}",
        )
    except Exception as e:
        logger.error(f"Error creating credit transaction: {e}")
        return HttpResponse(f"Error creating credit transaction: {e}", status=400)
