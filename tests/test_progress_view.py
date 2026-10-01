import json

from codex_harness_connect.server import progress_page


def test_progress_projection_preserves_cursor_gaps_without_private_transcript():
    page = {"session":{"session_id":"a"*32,"status":"completed","error":"PRIVATE","native_outcome":{"result":"PRIVATE"}},
            "next_cursor":9,"earliest_cursor":1,"truncated":False,"events":[
                {"cursor":1,"kind":"output","data":{"text":"PRIVATE"}},
                {"cursor":9,"kind":"native_protocol","data":{"kind":"result","result":"PRIVATE","errors":["PRIVATE"],"semantic_status":"succeeded","permission_denial_count":1}}]}
    result = progress_page(page)
    assert result["next_cursor"] == 9 and result["events"][0]["cursor"] == 9
    assert result["session"]["error_present"] is True
    assert result["events"][0]["data"]["permission_denial_count"] == 1
    assert "PRIVATE" not in json.dumps(result)
    assert "PRIVATE" in json.dumps(page)
