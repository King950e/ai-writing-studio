import os
import re
import sys

import cover_letter
import tailor_resume


def safe_folder_name(name):
    # Remove characters Windows doesn't allow in folder names, and trim spaces.
    cleaned = re.sub(r'[\\/:*?"<>|&]', "", name).strip()
    return cleaned or "application"


def save(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Saved {path}")


def main():
    if len(sys.argv) < 3:
        print('Usage: python apply.py <job_description_file_or_text> "<company name>"')
        sys.exit(1)

    job_arg = sys.argv[1]
    company = sys.argv[2]

    # Load everything first, so a mistake in work_history.json stops us before any slow AI calls.
    work_history = tailor_resume.load_work_history()
    job_description = tailor_resume.read_job_description(job_arg)

    # Make a folder for this application, named after the company.
    folder = safe_folder_name(company)
    os.makedirs(folder, exist_ok=True)

    # 1. Tailored resume
    print("Generating tailored resume... (a minute or two)")
    resume = tailor_resume.call_ollama(tailor_resume.build_prompt(work_history, job_description))
    save(os.path.join(folder, "resume.md"), resume)

    # 2. Cover letter
    print("\nGenerating cover letter... (a minute or two)")
    letter = cover_letter.call_ollama(cover_letter.build_prompt(work_history, job_description, company))
    save(os.path.join(folder, "cover_letter.md"), letter)

    print(f"\nDone. Your application packet for {company} is in the '{folder}' folder.")
    print("Read both files over before sending. Make sure every line is true.")


if __name__ == "__main__":
    main()
