"""Values signed for other modules under a label, as chat images are."""

from __future__ import annotations

from served import serving

ADDRESS = "https://example.com/kana.png"


async def test_a_signature_holds_for_its_label_and_value_alone():
    async with serving() as served:
        signature = served.access.sign("image", ADDRESS)
        assert served.access.verify("image", ADDRESS, signature)
        assert not served.access.verify("attachment", ADDRESS, signature)
        assert not served.access.verify(
            "image", "https://example.com/aqua.png", signature
        )
        changed = signature[:-1] + ("0" if signature[-1] != "0" else "1")
        assert not served.access.verify("image", ADDRESS, changed)
        # one with characters a digest never has is just wrong
        assert not served.access.verify("image", ADDRESS, "签名")
        # a colon in a label does not move where the label ends
        assert not served.access.verify(
            "image",
            "thumbnail:" + ADDRESS,
            served.access.sign("image:thumbnail", ADDRESS),
        )
