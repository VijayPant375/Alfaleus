"""
Phase 4: Scraper Service

Scrapes LinkedIn and Indeed for candidates based on job title and location.
Since both platforms heavily block unauthenticated/headless scrapers, this service
attempts a live fetch but falls back to returning structured mock data upon
encountering CAPTCHAs or blocks, ensuring the rest of the pipeline can still be tested.
"""

import asyncio
import logging
import urllib.parse
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("Playwright not installed (likely Python 3.13 greenlet build error). Scraper will use fallback.")
    PLAYWRIGHT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Mock Fallbacks
# ---------------------------------------------------------------------------

def _get_mock_candidates(title: str, location: Optional[str], source: str) -> List[Dict[str, Any]]:
    loc_str = f" in {location}" if location else ""
    if source == "linkedin":
        return [
            {
                "name": "Jane Doe",
                "current_title": title,
                "current_company": "Tech Innovators",
                "listed_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
                "experience_summary": f"Senior {title}{loc_str} with 6 years of experience building scalable backends.",
                "work_history": [
                    {"title": title, "company": "Tech Innovators", "duration_months": 40},
                    {"title": "Backend Developer", "company": "StartUp LLC", "duration_months": 24}
                ],
                "source": "linkedin",
                "profile_url": "https://linkedin.com/in/janedoe-mock",
                "confidence_level": "high"
            },
            {
                "name": "John Smith",
                "current_title": "Backend Engineer",
                "current_company": "Global Solutions",
                "listed_skills": ["Python", "Django", "SQL", "Redis"],
                "experience_summary": f"Backend Engineer{loc_str} focused on data processing.",
                "work_history": [
                    {"title": "Backend Engineer", "company": "Global Solutions", "duration_months": 18},
                    {"title": "Junior Developer", "company": "WebCorp", "duration_months": 12}
                ],
                "source": "linkedin",
                "profile_url": "https://linkedin.com/in/johnsmith-mock",
                "confidence_level": "high"
            }
        ]
    else:
        return [
            {
                "name": "Alice Wonderland",
                "current_title": f"Lead {title}",
                "current_company": "Fintech Inc",
                "listed_skills": ["Python", "Kubernetes", "Microservices", "Kafka"],
                "experience_summary": f"Lead {title}{loc_str} specializing in distributed systems.",
                "work_history": [
                    {"title": f"Lead {title}", "company": "Fintech Inc", "duration_months": 36},
                    {"title": "Senior Engineer", "company": "Fintech Inc", "duration_months": 24}
                ],
                "source": "indeed",
                "profile_url": "https://indeed.com/r/alicew-mock",
                "confidence_level": "high"
            },
            {
                "name": "Bob Builder",
                "current_title": "Junior Developer",
                "current_company": "Agency XYZ",
                "listed_skills": ["Python", "Flask", "HTML"],
                "experience_summary": f"Recent grad working as a Junior Developer{loc_str}.",
                "work_history": [
                    {"title": "Junior Developer", "company": "Agency XYZ", "duration_months": 6}
                ],
                "source": "indeed",
                "profile_url": "https://indeed.com/r/bobb-mock",
                "confidence_level": "medium"
            }
        ]

# ---------------------------------------------------------------------------
# LinkedIn Scraper (Playwright)
# ---------------------------------------------------------------------------

async def scrape_linkedin(title: str, location: Optional[str]) -> List[Dict[str, Any]]:
    """Scrape LinkedIn using Playwright."""
    logger.info("Starting LinkedIn scrape for '%s' in '%s'", title, location)
    
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available. Returning mock LinkedIn candidates.")
        return _get_mock_candidates(title, location, "linkedin")
    
    query = f"keywords={urllib.parse.quote(title)}"
    if location:
        query += f"&location={urllib.parse.quote(location)}"
    
    url = f"https://www.linkedin.com/search/results/people/?{query}"
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Use a short timeout since we're just checking if we can get through
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # Wait a moment for dynamic content
            await asyncio.sleep(3)
            
            # Check if we hit an auth wall or captcha (which is 99% likely without cookies)
            if "login" in page.url.lower() or "challenge" in page.url.lower() or await page.locator("form.login__form").count() > 0:
                logger.warning("LinkedIn blocked unauthenticated access. Falling back to mock data.")
                await browser.close()
                return _get_mock_candidates(title, location, "linkedin")
                
            # If by some miracle we got through, try to parse some basic info
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            
            results = []
            cards = soup.select(".reusable-search__result-container")
            for card in cards:
                name_elem = card.select_one(".entity-result__title-text a")
                title_elem = card.select_one(".entity-result__primary-subtitle")
                loc_elem = card.select_one(".entity-result__secondary-subtitle")
                
                if name_elem and title_elem:
                    name_clean = name_elem.text.strip().split("\n")[0].strip()
                    if "LinkedIn Member" in name_clean:
                        continue
                        
                    results.append({
                        "name": name_clean,
                        "current_title": title_elem.text.strip(),
                        "current_company": None, # Hard to reliably extract from just search results without clicking
                        "listed_skills": [],
                        "experience_summary": title_elem.text.strip() + (" in " + loc_elem.text.strip() if loc_elem else ""),
                        "work_history": [],
                        "source": "linkedin",
                        "profile_url": name_elem.get("href", "").split("?")[0],
                        "confidence_level": "medium"
                    })
            
            await browser.close()
            
            if not results:
                logger.warning("No LinkedIn results found or parsing failed. Falling back to mock data.")
                return _get_mock_candidates(title, location, "linkedin")
                
            return results

    except Exception as e:
        logger.warning("LinkedIn scrape failed (%s: %s). Falling back to mock data.", type(e).__name__, str(e))
        return _get_mock_candidates(title, location, "linkedin")

# ---------------------------------------------------------------------------
# Indeed Scraper (httpx + BeautifulSoup)
# ---------------------------------------------------------------------------

async def scrape_indeed(title: str, location: Optional[str]) -> List[Dict[str, Any]]:
    """Scrape Indeed using httpx and BeautifulSoup."""
    logger.info("Starting Indeed scrape for '%s' in '%s'", title, location)
    
    query_params = {"q": title}
    if location:
        query_params["l"] = location
        
    url = f"https://www.indeed.com/resumes?{urllib.parse.urlencode(query_params)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            
            if resp.status_code != 200:
                logger.warning("Indeed returned status %s. Falling back to mock data.", resp.status_code)
                return _get_mock_candidates(title, location, "indeed")
                
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Check for Cloudflare / Captcha
            if "Cloudflare" in resp.text or "captcha" in resp.text.lower() or "verify you are human" in resp.text.lower():
                logger.warning("Indeed presented a CAPTCHA/Block. Falling back to mock data.")
                return _get_mock_candidates(title, location, "indeed")
                
            results = []
            # Note: Indeed's DOM changes frequently. This is a best-effort structural parse.
            cards = soup.select(".rezemp-ResumeSearchCard")
            for card in cards:
                title_elem = card.select_one(".rezemp-ResumeSearchCard-title")
                name_elem = card.select_one(".rezemp-ResumeSearchCard-name")
                summary_elem = card.select_one(".rezemp-ResumeSearchCard-summary")
                
                if title_elem:
                    results.append({
                        "name": name_elem.text.strip() if name_elem else f"Candidate {len(results)+1}",
                        "current_title": title_elem.text.strip(),
                        "current_company": None,
                        "listed_skills": [],
                        "experience_summary": summary_elem.text.strip() if summary_elem else "",
                        "work_history": [],
                        "source": "indeed",
                        "profile_url": "https://indeed.com/resumes", # Actual links require parsing encrypted IDs
                        "confidence_level": "low" if not name_elem else "medium"
                    })
                    
            if not results:
                logger.warning("No Indeed results found (DOM likely changed). Falling back to mock data.")
                return _get_mock_candidates(title, location, "indeed")
                
            return results
            
    except Exception as e:
        logger.warning("Indeed scrape failed (%s: %s). Falling back to mock data.", type(e).__name__, str(e))
        return _get_mock_candidates(title, location, "indeed")

# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

async def run_scrapers(title: str, location: Optional[str]) -> List[Dict[str, Any]]:
    """Run both scrapers concurrently and merge results."""
    logger.info("Running all scrapers for '%s' in '%s'", title, location)
    
    # Run concurrently
    results = await asyncio.gather(
        scrape_linkedin(title, location),
        scrape_indeed(title, location),
        return_exceptions=True
    )
    
    all_candidates = []
    
    # Process LinkedIn results
    if isinstance(results[0], Exception):
        logger.error("LinkedIn scraper raised unhandled exception: %s", results[0])
    else:
        all_candidates.extend(results[0])
        
    # Process Indeed results
    if isinstance(results[1], Exception):
        logger.error("Indeed scraper raised unhandled exception: %s", results[1])
    else:
        all_candidates.extend(results[1])
        
    return all_candidates
