"""강의 노트 정리용 AI 프롬프트 템플릿"""
from pathlib import Path

LECTURE_NOTE_TEMPLATE = """
아래는 강의를 녹음하여 텍스트로 변환한 내용입니다.
당신은 이 내용을 옵시디언(Obsidian)에서 사용하기 가장 좋은 형태로 정리해주는 전문가입니다.
이 텍스트 전체를 논리적인 흐름에 따라 체계적인 마크다운 문서로 만들어 주세요.

아래 지침을 반드시 따라주세요:

1.  **자동 목차 생성:** 문서의 서론 바로 다음에, 옵시디언의 'Dynamic Table of Contents' 플러그인이 인식할 수 있도록 ` ```toc``` ` 코드 블록을 정확히 삽입해 주세요. 절대로 수동으로 목차 목록을 만들지 마세요.

2.  **구조화:** 전체 내용을 분석하여 의미 있는 대주제와 소주제로 나누고, 각각 마크다운 헤더(`#`, `##`, `###`)를 사용해 명확한 계층 구조를 만들어 주세요. 이 헤더들이 자동 목차의 기반이 됩니다.

3.  **상세한 내용:** 원본의 핵심 내용, 예시, 중요한 설명 등을 최대한 누락하지 말고 상세하게 포함해 주세요. 단순히 요약하는 것이 아니라, 내용을 재구성하고 체계화하는 것입니다.

4.  **가독성 향상:**
    - 중요한 키워드나 용어는 **볼드체**로 강조해 주세요.
    - 나열되는 항목은 글머리 기호(`-`)나 번호 매기기(`1.`)를 사용해 목록으로 만들어 주세요.
    - 특히, 강의의 핵심적인 팁, 경고, 중요한 정보는 옵시디언의 콜아웃(Callout) 문법(예: `> [!NOTE]`, `> [!IMPORTANT]`, `> [!TIP]`)을 활용하여 눈에 띄게 만들어주면 더욱 좋습니다.

5.  **코드 예제:** 만약 강의 내용 중에 코드나 명령어가 나온다면, 적절한 언어(예: `bash`, `javascript`, `python` 등)를 명시한 코드 블록(```)으로 정확하게 감싸주세요.

최종 결과물은 제가 옵시디언에 바로 복사해서 붙여넣을 수 있도록, 완성된 마크다운 전체를 하나의 코드 블록 안에 담아서 제공해 주세요.

---
[여기에 강의 녹음 텍스트를 붙여넣으세요]
---
"""


def create_ai_prompt_file(output_path: str | Path, content_text: str) -> Path | None:
    """AI 프롬프트가 포함된 텍스트 파일을 생성."""
    try:
        placeholder = "[여기에 강의 녹음 텍스트를 붙여넣으세요]"
        if placeholder in LECTURE_NOTE_TEMPLATE:
            final_content = LECTURE_NOTE_TEMPLATE.replace(placeholder, content_text)
        else:
            final_content = LECTURE_NOTE_TEMPLATE + "\n\n" + content_text

        output_path = Path(output_path)
        output_path.write_text(final_content, encoding='utf-8')
        return output_path
    except Exception as e:
        print(f"AI 프롬프트 파일 생성 실패: {e}")
        return None
