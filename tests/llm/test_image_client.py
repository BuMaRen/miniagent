import unittest

from bumaren_agent_workflow.llm.image_client import ImageClient, ImageResult, NotConfiguredImageClient


class NotConfiguredImageClientTests(unittest.TestCase):
    def test_generate_raises_not_implemented_with_guidance(self) -> None:
        client = NotConfiguredImageClient()
        with self.assertRaises(NotImplementedError) as ctx:
            client.generate("a cover for a short story")
        self.assertIn("ImageClient", str(ctx.exception))

    def test_is_an_image_client(self) -> None:
        self.assertIsInstance(NotConfiguredImageClient(), ImageClient)


class ImageResultTests(unittest.TestCase):
    def test_defaults(self) -> None:
        result = ImageResult(url="https://example.com/cover.png")
        self.assertEqual(result.mime_type, "image/png")
        self.assertIsNone(result.data_base64)
        self.assertEqual(result.meta, {})


if __name__ == "__main__":
    unittest.main()
