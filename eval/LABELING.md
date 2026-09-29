# Human Evaluation Labeling Guidelines

## Core Definition
- **apply**: "I would personally spend 20 minutes tailoring and submitting an application for this role."
- **skip**: The role is disqualified due to hard constraints or strong misalignment.
- **borderline**: Genuinely ambiguous cases where human recruiter deliberation would be necessary.

## Disqualification Reasons (`reason_tag`)
When marking a JD as `skip`, tag with one of the primary reasons:
- `seniority`: Candidate does not meet experience or title tier (e.g. Senior/Staff/Lead when candidate is Junior/Mid).
- `stack`: Required core tech stack is largely absent from candidate skills.
- `location`: Requires strictly on-site or unsupported jurisdiction.
- `domain`: Highly specialized niche required (e.g. high-frequency trading, specialized clinical).
- `company`: Unsuitable or blacklisted company profile.
- `pay`: Unrealistic compensation or unpaid role.
