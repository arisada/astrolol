import asyncio

from astrolol import main as main_mod


async def test_api_is_up_while_profile_restores(monkeypatch):
    release = asyncio.Event()
    done = asyncio.Event()

    async def slow_restore(state):
        await release.wait()
        done.set()

    monkeypatch.setattr(main_mod, "restore_last_profile", slow_restore)
    app = main_mod.create_app()
    async with app.router.lifespan_context(app):
        # Lifespan startup has completed (the server would be serving) but restore hasn't.
        assert not done.is_set()
        release.set()
        await app.state.profile_restore_task
        assert done.is_set()


async def test_failed_restore_does_not_break_startup(monkeypatch):
    async def broken_restore(state):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_mod, "restore_last_profile", broken_restore)
    app = main_mod.create_app()
    async with app.router.lifespan_context(app):
        await app.state.profile_restore_task


async def test_shutdown_cancels_pending_restore(monkeypatch):
    async def forever(state):
        await asyncio.Event().wait()

    monkeypatch.setattr(main_mod, "restore_last_profile", forever)
    app = main_mod.create_app()
    async with app.router.lifespan_context(app):
        pass
    assert app.state.profile_restore_task.done()
