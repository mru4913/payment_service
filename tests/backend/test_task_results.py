"""Task result extraction helpers."""

from common.task_results import extract_result_image_urls


def test_extract_result_image_urls_accepts_image_extensions_and_types() -> None:
    payload = {
        "query": {
            "results": [
                {"url": "https://cdn.example/a.png", "output_type": "png"},
                {"url": "https://cdn.example/b.webp?x=1", "output_type": "text"},
                {"url": "https://cdn.example/c.bin", "output_type": "text"},
                {"url": "https://cdn.example/a.png", "output_type": "png"},
            ]
        }
    }

    assert extract_result_image_urls(payload) == [
        "https://cdn.example/a.png",
        "https://cdn.example/b.webp?x=1",
    ]


def test_extract_result_image_urls_ignores_missing_query() -> None:
    assert extract_result_image_urls({}) == []
