import os
import json
import re
import pandas as pd
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_groq import ChatGroq


class UserProfiledCourseRecommender:
    def __init__(self, csv_path):
        load_dotenv()
        # Load courses dataset
        self.courses_df = pd.read_csv(csv_path)
        # Initialize embeddings and vector store
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self._prepare_vector_store()
        # Initialize LLM
        self.llm = ChatGroq(
            temperature=0.5,
            model_name="deepseek-r1-distill-llama-70b",
            max_tokens=2000
        )

    def _prepare_vector_store(self):
        # Create document representations for vector store
        documents = [
            (
                f"Course Title: {row['Course Title']}\n"
                f"Difficulty: {row['Difficulty']}\n"
                f"Domain: {row['Course Domain']}\n"
                f"Description: {row['Description']}\n"
                f"Hours: {row['Hours']}\n"
                f"Link: {row['Link']}"
            )
            for _, row in self.courses_df.iterrows()
        ]
        # Split documents for better semantic search
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=100)
        split_docs = text_splitter.create_documents(documents)
        # Create vector store and retriever
        self.vectorstore = FAISS.from_documents(split_docs, self.embeddings)
        self.retriever = self.vectorstore.as_retriever(search_kwargs={"k": 10})

    def extract_json(self, text):
        try:
            # Remove markdown formatting (```json and ```)
            text = re.sub(r'```json|```', '', text)
            # Fix common LLM JSON issues
            text = (
                text.replace('\\"', "'")
                    .replace('""', '"')
                    .replace('"', '"')
                    .replace('"', '"')
            )
            # Handle line breaks within strings
            text = re.sub(r',\s*\n\s*"', ', "', text)
            # Find JSON boundaries: first "{" and last "}"
            start = text.find('{')
            end = text.rfind('}') + 1
            json_str = text[start:end]
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(
                f"JSON Decode Error: {e}\nPartial JSON:\n{json_str[e.pos-50:e.pos+50]}")
            raise

    def recommend_courses(self, skill_ratings=None):
        """
        Recommend courses based on a comprehensive user profile and skill ratings.
        """
        try:

            # Format skill ratings for the prompt if available
            skill_analysis = ""
            if skill_ratings:
                skill_analysis = f"""
                SKILL RATINGS ANALYSIS:
                - Creative: {skill_ratings.get('creative', 'Not provided')}
                - Engagement: {skill_ratings.get('engagement', 'Not provided')}
                - Technical Proficiency: {skill_ratings.get('technical_proficiency', 'Not provided')}
                - Strategic Thinking: {skill_ratings.get('strategic_thinking', 'Not provided')}
                - Clarity: {skill_ratings.get('clarity', 'Not provided')}

                Use these skill ratings to:
                1. Match course difficulty levels with the user's technical proficiency
                2. Consider courses that align with their strengths
                3. Suggest courses that can help improve areas with lower ratings
                """

            # Prepare prompt for course recommendations
            prompt = f"""You are an AI Course Recommendation Specialist.


            {skill_analysis}

            COURSE RECOMMENDATION GUIDELINES:
            1. Analyze the user's background, goals, and learning preferences.
            2. Recommend 5-4 courses that precisely match the user's needs.
            3. Consider factors like:
            - Current skill level (based on skill ratings)
            - Career aspirations
            - Learning style
            - Time availability
            - Specific interests
            - Areas for improvement

            JSON OUTPUT FORMAT:
            ```json
            {{
                "recommendations": [
                    {{
                        "Course Title": "EXACT title from CSV",
                        "Difficulty": "Match exactly from CSV",
                        "Hours": "Number from CSV",
                        "Link": "Direct URL from CSV",
                        "Rationale": "Why this course matches the user's profile and skill ratings",
                        "Key Learning Outcomes": ["Outcome 1", "Outcome 2"],
                        "Skill Alignment": {{
                            "primary_skill": "Main skill this course addresses",
                            "difficulty_match": "How well the course difficulty matches user's technical level"
                        }}
                    }}
                ],
                "profile_analysis": {{
                    "strengths": ["Strength 1", "Strength 2"],
                    "areas_for_improvement": ["Area 1", "Area 2"],
                    "recommended_learning_path": "Brief learning path description based on skill ratings"
                }}
            }}
            ```
            CRITICAL INSTRUCTIONS:
            - USE ONLY COURSES FROM THE PROVIDED DATA.
            - DOUBLE-CHECK JSON SYNTAX: ensure commas between properties, no trailing commas, proper quotation marks, and valid array formatting.
            - Consider the user's skill ratings when recommending course difficulty levels.
            """
            # Generate recommendations using LLM
            response = self.llm.invoke(prompt)
            # Extract and parse JSON from the LLM response
            recommendations = self.extract_json(response.content)
            return json.dumps(recommendations, indent=2)
        except Exception as e:
            return json.dumps({
                "error": str(e),
                "details": "Failed to generate recommendations",
                "recommendations": []
            }, indent=2)
