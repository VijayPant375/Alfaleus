import logging
import os
import resend
from app.models.candidate import Candidate
from app.models.job import Job

logger = logging.getLogger(__name__)

# Initialize resend API key
resend.api_key = os.getenv("RESEND_API_KEY")

async def send_interview_invite(candidate: Candidate, job: Job) -> bool:
    """
    Send an interview invite email with a deep link to the mobile app.
    Returns True if sent successfully, False otherwise.
    Does not raise exceptions on failure.
    """
    if not resend.api_key:
        logger.warning("RESEND_API_KEY is not set. Skipping email send.")
        return False
        
    if not candidate.interview_token:
        logger.error(f"Candidate {candidate.id} does not have an interview_token.")
        return False

    deep_link = f"alfaleus://interview/{candidate.interview_token}"
    
    # In this MVP, we don't have the candidate's real email from the scraper.
    # We use a test address provided by Resend.
    to_email = "delivered@resend.dev"
    
    html_content = f"""
    <h1>You've been invited to interview!</h1>
    <p>Hi {candidate.name or 'Candidate'},</p>
    <p>You have been shortlisted for the <strong>{job.title}</strong> position.</p>
    <p>Please click the link below to start your interview in the Alfaleus app:</p>
    <a href="{deep_link}">{deep_link}</a>
    """
    
    try:
        resend.Emails.send({
            "from": "Alfaleus <onboarding@resend.dev>",
            "to": to_email,
            "subject": f"Interview Invitation: {job.title}",
            "html": html_content
        })
        logger.info("Sent email to %s for candidate %s", to_email, candidate.id)
        return True
    except Exception as e:
        logger.error("Failed to send email for candidate %s: %s", candidate.id, str(e))
        return False
