from app.core.db import DbSession
from app.payment_methods.repository import PaymentMethodRepository


def get_payment_method_repo(db: DbSession) -> PaymentMethodRepository:
    return PaymentMethodRepository(db)
