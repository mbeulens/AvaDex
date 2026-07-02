import base64

from avadex.tools.builtin import attach_image_tool, MAX_IMAGE_BYTES


def test_attach_image_missing_path():
    result = attach_image_tool({})
    assert result.is_error
    assert "path" in result.content.lower()


def test_attach_image_not_found(tmp_path):
    result = attach_image_tool({"path": str(tmp_path / "nope.png")})
    assert result.is_error
    assert "not found" in result.content.lower()


def test_attach_image_not_a_file(tmp_path):
    result = attach_image_tool({"path": str(tmp_path)})
    assert result.is_error
    assert "not a file" in result.content.lower()


def test_attach_image_unsupported_extension(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    result = attach_image_tool({"path": str(f)})
    assert result.is_error
    assert "unsupported" in result.content.lower()


def test_attach_image_too_large(tmp_path):
    f = tmp_path / "huge.png"
    f.write_bytes(b"\x89PNG" + b"x" * (MAX_IMAGE_BYTES + 1))
    result = attach_image_tool({"path": str(f)})
    assert result.is_error
    assert "too large" in result.content.lower()


def test_attach_image_returns_image_block(tmp_path):
    raw = b"\x89PNG\r\n\x1a\nfake-pixels"
    f = tmp_path / "pic.png"
    f.write_bytes(raw)

    result = attach_image_tool({"path": str(f)})

    assert not result.is_error
    assert isinstance(result.content, list)
    image_block = result.content[0]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert image_block["source"]["data"] == base64.b64encode(raw).decode("ascii")
    # A human/model-readable text block follows the image, naming the file.
    text_block = result.content[1]
    assert text_block["type"] == "text"
    assert "pic.png" in text_block["text"]


def test_attach_image_jpeg_media_type(tmp_path):
    f = tmp_path / "photo.jpeg"
    f.write_bytes(b"\xff\xd8\xff\xe0jpegdata")
    result = attach_image_tool({"path": str(f)})
    assert not result.is_error
    assert result.content[0]["source"]["media_type"] == "image/jpeg"
