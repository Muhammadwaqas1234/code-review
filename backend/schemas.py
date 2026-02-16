from pydantic import BaseModel, HttpUrl


class ReviewRequest(BaseModel):
    repo_url: HttpUrl
    roles_text: str


class ReviewResponse(BaseModel):
    reviews: dict
    score: str
    report: str
