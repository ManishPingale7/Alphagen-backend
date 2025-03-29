from fastapi import APIRouter, HTTPException
from app.edu.course_recommender import UserProfiledCourseRecommender
from groq import Groq
from dotenv import load_dotenv
import os
import json
from .schemas import SkillRatings
from pydantic import BaseModel
from .crud import add_skill_ratings, retrieve_latest_skill_ratings
import re

load_dotenv()

router = APIRouter(prefix="/edu", tags=["Education task APIs"])
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

recommender = UserProfiledCourseRecommender('data/courses.csv')


@router.get("/skill_ratings")
async def get_skill_ratings():
    skill_ratings = await retrieve_latest_skill_ratings()
    if skill_ratings:
        return skill_ratings
    raise HTTPException(status_code=404, detail="SkillRatings not found")


@router.post("/skill-ratings")
async def submit_skill_ratings(ratings: SkillRatings):
    new_skill_ratings = await add_skill_ratings(ratings)
    return new_skill_ratings


@router.post("/course-recommendation")
async def course_recommendation_endpoint():
    try:
        # Fetch the latest skill ratings
        skill_ratings = await retrieve_latest_skill_ratings()
        
        # Generate recommendations with both user profile and skill ratings
        recommendations = recommender.recommend_courses(skill_ratings)
        
        # Convert the recommendations JSON string to a JSON object
        return json.loads(recommendations)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcq-test")
async def generate_mcq_test():
    # Parse categories and calculate questions per category
    

    prompt = (
        f"Create a 20-question multiple-choice test on 'Content Creation' with challenging, thought-provoking questions. "
        f"Divide the test evenly into 5 categories: creativity,clarity,engagement,technical_proficiency,strategic_thinking "
        f"(4 questions per category). "
        f"Each question must include 4 concise answer options labeled A, B, C, D, with one correct answer. "
        f"\nGuidelines for high-quality questions:\n"
        f"1. Focus on application of knowledge rather than simple recall\n"
        f"2. Ensure all wrong answers (distractors) are plausible and of similar length to the correct answer\n"
        f"3. Use clear, precise language without ambiguity\n"
        f"4. Test higher-order thinking skills (analysis, evaluation, synthesis)\n"
        f"5. Avoid negative phrasing like 'Which is NOT...'\n"
        f"6. Include scenario-based questions that require critical thinking\n"
        f"\nOutput the result as a single valid JSON object using the following structure and nothing else:\n\n"
        "{\"questions\": [\n"
        "    {\"characteristic\": \"...\", \"question\": \"...\", \"options\": [\"A. ...\", \"B. ...\", \"C. ...\", \"D. ...\"], "
        "\"correct_answer\": \"...\", \"explanation\": \"Brief explanation of why this answer is correct\"},\n"
        "    ...\n"
        "]}"
    )

    completion = client.chat.completions.create(
        model="deepseek-r1-distill-llama-70b",
        messages=[
            {"role": "system", "content": "You are an expert educator specializing in creating high-quality assessment questions that test deep understanding and critical thinking."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,  # Slightly higher temperature for more creative questions
        max_completion_tokens=3000,  # Increased for accommodating explanations
        top_p=0.95,
        stream=False,
        reasoning_format="raw"
    )

    response_text = completion.choices[0].message.content

    print(response_text)  # Keep this for debugging

    # Try to extract JSON from triple-backticks (```json ... ```)
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        # Fallback: extract the substring starting at the first '{' and ending at the last '}'
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        if json_start != -1 and json_end != -1:
            json_str = response_text[json_start:json_end+1]
        else:
            return {"error": "Failed to find JSON structure in the LLM response."}

    cleaned_json_str = clean_json(json_str)

    try:
        extracted_json = json.loads(cleaned_json_str)
        
        # Validate the structure of the response
        if "questions" not in extracted_json or not extracted_json["questions"]:
            return {"error": "Invalid response structure: missing questions array"}
            
 
            
        return {"response": extracted_json}
    except json.JSONDecodeError as e:
        # More advanced cleaning attempt for difficult JSON cases
        try:
            # Try to fix common JSON formatting issues
            fixed_json_str = re.sub(r',\s*}', '}', cleaned_json_str)
            fixed_json_str = re.sub(r',\s*]', ']', fixed_json_str)
            extracted_json = json.loads(fixed_json_str)
            return {"response": extracted_json}
        except json.JSONDecodeError:
            return {"error": f"JSON parsing error: {str(e)}\n{response_text[:500]}..."}

    return {"response": extracted_json}


def clean_json(json_str: str) -> str:
    cleaned = re.sub(r',\s*([\]}])', r'\1', json_str)
    return cleaned
