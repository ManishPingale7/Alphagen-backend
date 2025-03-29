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

    def recommend_courses(self, skill_ratings):
        """
        Recommend courses based on user skill ratings.
        """
        try:
            # Create a query based on skill ratings
            query = f"User with skills: "
            for skill, rating in skill_ratings.items():
                if skill != "id":  # Skip the ID field
                    query += f"{skill}: {rating}, "
            
            # Retrieve relevant courses using the vector store
            relevant_docs = self.retriever.invoke(query)
            courses_context = "\n\n".join([doc.page_content for doc in relevant_docs])
            
            # Prepare prompt for course recommendations
            prompt = f"""You are an AI Course Recommendation Specialist.

AVAILABLE COURSES (ONLY RECOMMEND FROM THIS LIST):
{courses_context}

USER SKILL RATINGS:
{json.dumps(skill_ratings, indent=2)}

COURSE RECOMMENDATION GUIDELINES:
1. CRITICALLY IMPORTANT: ONLY recommend courses from the AVAILABLE COURSES list provided above.
2. Do NOT make up or hallucinate any course titles, links, or details.
3. Recommend 4-6 courses that match the user's skill levels and strength and weakness.
4. For lower-rated skills, recommend beginner-friendly courses.
5. For higher-rated skills, recommend more advanced courses.

JSON OUTPUT FORMAT:
```json
{{
    "recommendations": [
        {{
            "Course Title": "EXACT title from the available courses list",
            "Difficulty": "EXACT difficulty level from the available courses",
            "Hours": "EXACT hours from the available courses",
            "Link": "EXACT link from the available courses",
            "Rationale": "Why this course matches the user's skills profile",
            "Key Learning Outcomes": ["Outcome 1", "Outcome 2"]
        }}
    ],
    "profile_analysis": {{
        "strengths": ["Skills rated highest"],
        "areas_for_improvement": ["Skills rated lowest"],
        "recommended_learning_path": "Brief learning path description"
    }}
}}
```

CRITICAL INSTRUCTIONS:
- ONLY USE COURSES FROM THE PROVIDED AVAILABLE COURSES LIST.
- VERIFY each recommended course exists in the AVAILABLE COURSES list.
- If you're unsure if a course exists, DO NOT recommend it.
- DOUBLE-CHECK JSON syntax for validity.
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
