from pydantic import BaseModel


class SkillRatings(BaseModel):
    creative: str
    engagement: str
    technical_proficiency: str
    strategic_thinking: str
    clarity: str
