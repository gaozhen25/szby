from urllib.parse import quote, urlencode

from ..runtime.collector import MemoryStore, build_public_profile_url, build_safe_creator
from ..runtime.context import source_keyword_var
from ..vendor import tools as utils
from ..vendor.user_hash import anonymize_user_id, mask_nickname


class XhsStoreFactory:
    @staticmethod
    def create_store():
        return MemoryStore()


def _note_url(note_id, xsec_token, xsec_source):
    encoded_note_id = quote(str(note_id or ""), safe="-._~")
    base_url = f"https://www.xiaohongshu.com/explore/{encoded_note_id}"
    token = str(xsec_token or "").strip()
    source = str(xsec_source or "").strip()
    if not token or not source:
        return base_url
    return f"{base_url}?{urlencode({'xsec_token': token, 'xsec_source': source})}"


async def update_xhs_note(note_item):
    user = note_item.get("user") or {}
    metrics = note_item.get("interact_info") or {}
    note_id = note_item.get("note_id")
    await MemoryStore().store_content({
        "note_id": note_id,
        "type": note_item.get("type"),
        "title": note_item.get("title") or note_item.get("desc", "")[:255],
        "desc": note_item.get("desc", ""),
        "time": note_item.get("time"),
        "creator_hash": anonymize_user_id(user.get("user_id")),
        "nickname": mask_nickname(user.get("nickname")),
        "display_name": str(user.get("nickname") or "").strip()[:100],
        "profile_url": build_public_profile_url("xhs", user.get("user_id")),
        "liked_count": metrics.get("liked_count"),
        "collected_count": metrics.get("collected_count"),
        "comment_count": metrics.get("comment_count"),
        "share_count": metrics.get("share_count"),
        "note_url": _note_url(
            note_id,
            note_item.get("xsec_token"),
            note_item.get("xsec_source"),
        ),
        "source_keyword": source_keyword_var.get(),
    })


async def update_xhs_note_comment(note_id, comment_item):
    user = comment_item.get("user_info") or {}
    await MemoryStore().store_comment({
        "comment_id": comment_item.get("id"), "note_id": note_id,
        "content": comment_item.get("content"),
        "creator_hash": anonymize_user_id(user.get("user_id")),
        "nickname": mask_nickname(user.get("nickname")),
        "like_count": comment_item.get("like_count", 0),
    })


async def batch_update_xhs_note_comments(note_id, comments):
    for comment in comments or []:
        await update_xhs_note_comment(note_id, comment)


async def save_creator(user_id, creator):
    if not creator:
        return
    basic = creator.get("basicInfo") or {}
    counts = {item.get("type"): item.get("count") for item in creator.get("interactions") or []}
    await MemoryStore().store_creator(
        build_safe_creator(
            "xhs",
            user_id,
            {
                "nickname": basic.get("nickname"),
                "avatar_url": basic.get("imageb") or basic.get("images") or basic.get("avatar"),
                "bio": basic.get("desc") or basic.get("description"),
                "following_count": counts.get("follows"),
                "fans_count": counts.get("fans"),
                "interaction_count": counts.get("interaction"),
            },
            raw_data=creator,
        )
    )


async def update_xhs_note_image(*args, **kwargs): return None
async def update_xhs_note_video(*args, **kwargs): return None
