import json
import sys

# Reuse the fixed helpers from tailor_resume.py so both tools behave the same:
# UTF-8 files, template check, thinking turned off, bigger context, empty-answer check.
from tailor_resume import call_ollama, load_work_history, read_job_description

OUTPUT_FILE = "cover_letter.md"


def build_prompt(work_history, job_description, company):
    name = work_history.get("name", "")
    return f"""You are a cover letter writing assistant. Below is a candidate's full work history as JSON,
and a job description. Write a natural, concise THREE-paragraph cover letter for the company "{company}",
tailored to the job description. Reference specific relevant experience from the work history.

Rules:
- Do NOT invent any experience, numbers, tools, or certifications not present in the work history.
- Address it "Dear Hiring Manager,".
- Sign it "Sincerely," followed by {name}. Never use placeholders like [Your Name] or [Date].
- Output only the letter, with no preamble or explanation.

WORK HISTORY:
{json.dumps(work_history, indent=2)}

JOB DESCRIPTION:
{job_description}
"""


def main():
    if len(sys.argv) < 3:
        print('Usage: python cover_letter.py <job_description_file_or_text> "<company name>"')
        sys.exit(1)

    job_description = read_job_description(sys.argv[1])
    company = sys.argv[2]
    work_history = load_work_history()

    print("Writing your cover letter... this can take a minute or two.")
    result = call_ollama(build_prompt(work_history, job_description, company))
    print(result)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\nSaved to {OUTPUT_FILE}")
    print("Read it over before sending. Make sure every line is true.")


if __name__ == "__main__":
    main()
