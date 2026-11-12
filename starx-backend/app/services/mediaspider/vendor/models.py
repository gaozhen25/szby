from pydantic import BaseModel


class NoteUrlInfo(BaseModel):
    note_id: str
    xsec_token: str = ""
    xsec_source: str = ""


class VideoUrlInfo(BaseModel):
    aweme_id: str = ""
    video_id: str = ""
    url_type: str = "normal"


class CreatorUrlInfo(BaseModel):
    user_id: str = ""
    sec_user_id: str = ""
    xsec_token: str = ""
    xsec_source: str = ""
