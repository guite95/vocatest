import json
import os
import random
import google.generativeai as genai
from prompts import EXTRACT_PAIRS_PROMPT, GRADE_PROMPT

# Gemini 설정
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

class QuizService:
    @staticmethod
    def extract_words_from_text(text: str):
        """텍스트에서 단어 쌍을 추출하여 JSON 객체 리스트로 반환"""
        try:
            prompt = EXTRACT_PAIRS_PROMPT.format(text=text)
            response = model.generate_content(prompt)
            cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            print(f"AI Extraction Error: {e}")
            return []

    @staticmethod
    def generate_quiz_from_json(word_data_list: list, count: int = 40):
        """
        이미 파싱된 JSON 데이터 리스트(word_data_list)를 합쳐서 퀴즈 생성
        word_data_list: [[{'en':..., 'kr':...}, ...], [{'en':..., 'kr':...}]]
        """
        unique_words_map = {}
        for data in word_data_list:
            if isinstance(data, list):
                for item in data:
                    # 영단어 기준 중복 제거 (대소문자 무시)
                    key = item.get('en', '').strip().lower()
                    if key and key not in unique_words_map:
                        unique_words_map[key] = item
        
        all_words = list(unique_words_map.values())
        
        # 셔플 및 개수 제한
        random.shuffle(all_words)
        selected_pairs = all_words[:count]
        
        # 비율 계산 (27:13)
        en_to_kr_count = int(len(selected_pairs) * (27/40))
        
        final_quiz = []
        for i, pair in enumerate(selected_pairs):
            en_val = pair.get('en', '').split('/')[0].strip()
            kr_val = pair.get('kr', '').split('/')[0].strip()
            
            if not en_val or not kr_val: continue

            if i < en_to_kr_count:
                final_quiz.append({
                    "id": i + 1,
                    "question": en_val,
                    "answer_key": kr_val,
                    "type": "en_to_kr"
                })
            else:
                final_quiz.append({
                    "id": i + 1,
                    "question": kr_val,
                    "answer_key": en_val,
                    "type": "kr_to_en"
                })
        
        random.shuffle(final_quiz)
        for idx, q in enumerate(final_quiz): q['id'] = idx + 1
        
        return final_quiz, len([q for q in final_quiz if q['type'] == 'en_to_kr']), len([q for q in final_quiz if q['type'] == 'kr_to_en'])

    @staticmethod
    def grade_answers(answers: list):
        """사용자 답안 채점"""
        try:
            prompt = GRADE_PROMPT.format(json_data=json.dumps(answers, ensure_ascii=False))
            response = model.generate_content(prompt)
            cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            raise Exception(f"AI Grading Error: {str(e)}")