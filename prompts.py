# AI 프롬프트 관리 파일

EXTRACT_PAIRS_PROMPT = """
Analyze the provided text and extract English-Korean vocabulary pairs for a quiz database.

Strict Output Rules:
1. Return ONLY a valid JSON array. No Markdown code blocks (```).
2. Each item must be an object with "en" (English word) and "kr" (Korean meaning).
3. Clean the data:
   - Remove numbering (e.g., "1. Apple" -> "Apple").
   - Remove part-of-speech tags if they clutter the word.
   - If there are multiple meanings, combine them in the "kr" field.
4. Ignore non-vocabulary lines (headers, page numbers, instructions).

Source Text:
{text}
"""

GRADE_PROMPT = """
You are an English teacher grading a vocabulary test.

Rules:
1. en_to_kr: If the user's Korean meaning is contextually similar, mark true.
2. kr_to_en: If the user provides a valid synonym, mark true. Spelling must be correct.
3. Return a RAW JSON array.

Data:
{json_data}

Output Format:
[
    {{"question": "...", "user_answer": "...", "correct_answer": "...", "is_correct": true}},
    ...
]
"""