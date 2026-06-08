from fastapi import APIRouter, Depends, HTTPException
import uuid
import os

from app.core import db
from app.core.atrs import ATRSService
from app.models.vault import VaultEntryCreate, VaultEntryRead, CredentialType
from app.services.vault import VaultService, make_vault_row_writer, make_vault_row_reader, make_vault_lister, make_vault_updater, make_credential_access_writer
from app.services import litellm_service

router = APIRouter()

RA1_OWNER_ID = os.environ.get("RA1_OWNER_ID", "")


def get_pool():
    return db.get_pool()


def get_atrs(pool=Depends(get_pool)) -> ATRSService:
    async def _outbox_writer(row: dict) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO atrs_outbox (payload, created_at) VALUES ($1, NOW())",
                row,
            )
    return ATRSService(outbox_writer=_outbox_writer)


def get_vault_service(pool=Depends(get_pool), atrs: ATRSService = Depends(get_atrs)) -> VaultService:
    row_writer = make_vault_row_writer(pool, atrs)
    row_reader = make_vault_row_reader(pool)
    lister = make_vault_lister(pool)
    updater = make_vault_updater(pool)
    cred_log = make_credential_access_writer()
    return VaultService(
        row_writer=row_writer,
        row_reader=row_reader,
        lister=lister,
        updater=updater,
        atrs=atrs,
        credential_access_writer=cred_log,
    )


@router.post("/keys", response_model=VaultEntryRead)
async def store_key(
    entry: VaultEntryCreate,
    vault_service: VaultService = Depends(get_vault_service),
):
    if entry.credential_type != CredentialType.MODEL_API_KEY:
        raise HTTPException(status_code=400, detail="Only model_api_key credentials supported")
    result = await vault_service.create(RA1_OWNER_ID, entry)
    await litellm_service.update_models_for_provider(entry.label, entry.value)
    return result


@router.get("/keys", response_model=list[VaultEntryRead])
async def list_keys(
    vault_service: VaultService = Depends(get_vault_service),
):
    return await vault_service.list_for_owner(RA1_OWNER_ID)


@router.delete("/keys/{vault_id}")
async def revoke_key(
    vault_id: uuid.UUID,
    vault_service: VaultService = Depends(get_vault_service),
):
    return await vault_service.revoke(RA1_OWNER_ID, vault_id)