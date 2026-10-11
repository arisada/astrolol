"""Security plugin — users, guest mode, API tokens, allowed origins."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from astrolol.core.auth import AclRule, Level
from astrolol.core.plugin_api import Plugin, PluginContext, PluginManifest

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger()

_V = Level.VIEWER


class SecurityPlugin:
    manifest = PluginManifest(
        id="security",
        name="Security",
        version="0.1.0",
        description="Sign-in, read-only guest access, API tokens and allowed origins.",
        nav_group="settings",
        acl_rules=[
            AclRule("/plugins/security/me/password", _V, ("POST",)),
            AclRule("/plugins/security/**", Level.ADMIN),
        ],
    )

    def setup(self, app: "FastAPI", ctx: PluginContext) -> None:
        from astrolol.config.settings import settings
        from astrolol.plugins.security.api import router
        from astrolol.plugins.security.authorizer import SecurityAuthorizer, load_service_token
        from astrolol.plugins.security.models import SecuritySettings
        from astrolol.plugins.security.store import SecurityStore

        store = SecurityStore(settings.security_file)
        authorizer = SecurityAuthorizer(
            store,
            lambda: ctx.get_plugin_settings("security", SecuritySettings),
            service_token=load_service_token(settings.service_token_file),
        )
        app.state.security = authorizer
        app.state.authorizer = authorizer
        app.state.origin_providers.append(
            lambda: ctx.get_plugin_settings("security", SecuritySettings).allowed_origins
        )
        app.include_router(router)
        logger.info("security.ready", enforcing=authorizer.enforcing())

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> Plugin:
    return SecurityPlugin()
