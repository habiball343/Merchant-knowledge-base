from fastapi import Request

from app.container import Container
from app.services.chat_service import ChatService
from app.services.ingest_service import IngestService


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_ingest_service(request: Request) -> IngestService:
    return request.app.state.ingest_service


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service
