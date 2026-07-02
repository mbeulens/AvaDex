from avadex.context import estimate_tokens, SAFETY_FACTOR


def test_plain_string_token_count_unchanged():
    # Regression guard: strings must still be counted len/4 * safety.
    assert estimate_tokens("x" * 400) == int(400 / 4 * SAFETY_FACTOR)


def test_image_in_tool_result_counts_nominal_not_base64_length():
    big_b64 = "A" * 400_000  # ~120k tokens if counted as raw text
    msg = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": big_b64}},
            {"type": "text", "text": "attached"},
        ]},
    ]}
    assert estimate_tokens(msg) < 5000


def test_direct_image_block_counts_nominal():
    big_b64 = "B" * 400_000
    msg = {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": big_b64}},
    ]}
    assert estimate_tokens(msg) < 5000


def test_two_images_cost_more_than_one():
    small = {"type": "image", "source": {"type": "base64", "data": "A" * 100}}
    one = {"role": "user", "content": [small]}
    two = {"role": "user", "content": [small, small]}
    assert estimate_tokens(two) > estimate_tokens(one)
