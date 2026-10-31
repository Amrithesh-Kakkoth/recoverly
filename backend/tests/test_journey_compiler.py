import json

from httpx import ASGITransport, AsyncClient

from app.journeys.compiler import compile_journey, summarize
from app.journeys.default import DEFAULT_JOURNEY
from app.main import app
from tests.conftest import sign_in

GOOD = json.dumps(DEFAULT_JOURNEY)
BAD = json.dumps({**DEFAULT_JOURNEY, "start": "nowhere"})


def scripted(*replies):
    seen = []
    it = iter(replies)

    async def llm(messages):
        seen.append(list(messages))
        return next(it)
    llm.seen = seen
    return llm


async def test_valid_first_try():
    r = await compile_journey("recover carts", scripted(GOOD))
    assert r.definition == DEFAULT_JOURNEY and r.errors == []


async def test_repairs_after_lint_failure_and_sends_errors_back():
    llm = scripted(BAD, "not json", GOOD)
    r = await compile_journey("x", llm)
    assert r.definition and len(llm.seen) == 3
    assert "start step 'nowhere'" in llm.seen[1][-1]["content"]


async def test_gives_up_after_two_repairs():
    llm = scripted(BAD, BAD, BAD)
    r = await compile_journey("x", llm)
    assert r.definition is None and r.errors and len(llm.seen) == 3


def test_summary_is_generated_from_the_json():
    s = summarize(DEFAULT_JOURNEY)
    assert s[0].startswith("Starts when checkout abandoned") and "at least 20" in s[0]
    assert any("Wait up to 30 minutes or until the customer pays" in x for x in s)
    assert any("up to 10% off" in x for x in s)


async def test_api_save_list_and_compile():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await sign_in(c)
        bad = await c.post("/api/journeys", json={"definition": json.loads(BAD)})
        assert bad.status_code == 422 and bad.json()["detail"]["errors"]
        ok = await c.post("/api/journeys", json={"definition": DEFAULT_JOURNEY, "source_prompt": "p"})
        assert ok.status_code == 200
        listed = (await c.get("/api/journeys")).json()
        assert listed[1]["version"] == 1 and listed[1]["summary"] and listed[1]["source_prompt"] == "p"
        app.state.llm = None
        assert (await c.post("/api/journeys/compile", json={"prompt": "x"})).status_code == 503
        app.state.llm = scripted(GOOD)
        out = (await c.post("/api/journeys/compile", json={"prompt": "x"})).json()
        assert out["definition"] and out["errors"] == [] and out["summary"]
