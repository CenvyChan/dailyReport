from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.services.group_file import GroupFileError, publish_group_file


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class GroupFilePublishTests(SimpleTestCase):
    def _post(self, calls):
        def post(url, **kwargs):
            calls.append(("post", url, kwargs))
            if url.endswith("/uploadInfos/query"):
                return FakeResponse(payload={
                    "uploadKey": "upload-key",
                    "headerSignatureInfo": {
                        "headers": {
                            "Authorization": "OSS signature",
                            "Content-Type": "application/json",
                        },
                        "resourceUrls": ["https://oss.example/file"],
                    },
                })
            if url.endswith("/files/commit"):
                return FakeResponse(payload={"dentry": {"id": "100"}})
            if url.endswith("/files/send"):
                return FakeResponse(payload={"file": {"id": "200", "name": "日报.xlsx"}})
            raise AssertionError(f"unexpected URL {url}")
        return post

    def test_upload_commit_send_and_delete_source_copy(self):
        calls = []
        with patch("integrations.services.group_file.requests.post", side_effect=self._post(calls)), \
             patch("integrations.services.group_file.requests.put",
                   side_effect=lambda url, **kwargs: (calls.append(("put", url, kwargs)) or FakeResponse())), \
             patch("integrations.services.group_file.requests.delete",
                   side_effect=lambda url, **kwargs: (calls.append(("delete", url, kwargs)) or FakeResponse())):
            result = publish_group_file(
                "token", open_conversation_id="cid", union_id="u1",
                space_id="space1", file_name="日报.xlsx", blob=b"abc",
            )

        self.assertEqual(result["groupId"], "200")
        self.assertEqual(result["sourceDentryId"], "100")
        put_call = next(call for call in calls if call[0] == "put")
        # 头签名把 Content-Type 计入待签串，必须剔除。
        self.assertNotIn("Content-Type", put_call[2]["headers"])
        send_call = next(call for call in calls if call[0] == "post" and call[1].endswith("/files/send"))
        self.assertEqual(send_call[2]["json"]["dentryId"], "100")
        delete_call = next(call for call in calls if call[0] == "delete")
        self.assertIn("/dentries/100", delete_call[1])

    def test_send_failure_marks_stage_and_does_not_delete_source(self):
        calls = []
        def post(url, **kwargs):
            calls.append(("post", url, kwargs))
            if url.endswith("/uploadInfos/query"):
                return FakeResponse(payload={
                    "uploadKey": "upload-key",
                    "headerSignatureInfo": {
                        "headers": {"Authorization": "sig"},
                        "resourceUrls": ["https://oss.example/file"],
                    },
                })
            if url.endswith("/files/commit"):
                return FakeResponse(payload={"dentry": {"id": "100"}})
            if url.endswith("/files/send"):
                return FakeResponse(status_code=500, text="server error")
            raise AssertionError(url)

        with patch("integrations.services.group_file.requests.post", side_effect=post), \
             patch("integrations.services.group_file.requests.put",
                   side_effect=lambda url, **kwargs: FakeResponse()), \
             patch("integrations.services.group_file.requests.delete") as delete:
            with self.assertRaises(GroupFileError) as ctx:
                publish_group_file(
                    "token", open_conversation_id="cid", union_id="u1",
                    space_id="space1", file_name="日报.xlsx", blob=b"abc",
                )
        self.assertEqual(ctx.exception.stage, "send")
        delete.assert_not_called()

    def test_upload_failure_marks_stage_upload(self):
        with patch("integrations.services.group_file.requests.post", side_effect=self._post([])), \
             patch("integrations.services.group_file.requests.put",
                   return_value=FakeResponse(status_code=403, text="signature mismatch")):
            with self.assertRaises(GroupFileError) as ctx:
                publish_group_file(
                    "token", open_conversation_id="cid", union_id="u1",
                    space_id="space1", file_name="日报.xlsx", blob=b"abc",
                )
        self.assertEqual(ctx.exception.stage, "upload")
