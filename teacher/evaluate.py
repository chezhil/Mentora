import sys
import json
from shared.models import Question, StudentResponse
from teacher.engine import evaluate

def run_fixture(fixture_path: str):
    with open(fixture_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    question = Question.model_validate(data['question'])
    response = StudentResponse.model_validate(data['response'])
    
    print("Evaluating Student Response...")
    try:
        result = evaluate(question, response)
        print("\n--- EVALUATION RESULT ---")
        print(result.model_dump_json(indent=2))
    except Exception as e:
        print(f"Error during evaluation: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m teacher.evaluate <fixture.json>")
        sys.exit(1)
    run_fixture(sys.argv[1])
