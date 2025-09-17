import asyncio
import json
import csv
import os
import time
import sys
import subprocess
import random
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse, urljoin, urlencode, parse_qs
from playwright.async_api import async_playwright

# -----------------------
# File paths
# -----------------------
cookies_path = Path("cookies.json")
output_csv = Path("linkedin_engineering_results.csv")

# -----------------------
# Helpers
# -----------------------
def ask_question(prompt_text: str) -> str:
    return input(prompt_text)

async def delay(ms: int):
    await asyncio.sleep(ms / 1000)

def save_to_csv(rows):
    headers = [
        "Name", "Title", "Location", "Education", "Profile URL",
        "Total Experience", "Experience Details", "Skills"
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "Name": r.get("name", "N/A"),
                "Title": r.get("title", "N/A"),
                "Location": r.get("location", "N/A"),
                "Education": r.get("education", "N/A"),
                "Profile URL": r.get("url", ""),
                "Total Experience": r.get("total_experience", "N/A"),
                "Experience Details": r.get("experience_details", "N/A"),
                "Skills": r.get("skills", "N/A")
            })
    print(f"✅ Data saved to {output_csv}")

def open_excel(file_path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", file_path])
        else:
            subprocess.run(["xdg-open", file_path])
        print(f"📊 Opened Excel file.")
    except Exception as e:
        print(f"❌ Could not open Excel: {e}")

async def auto_scroll(page, step=600, max_rounds=30, wait_ms=1500):
    """Slow incremental scroll to trigger lazy-load."""
    try:
        last_height = await page.evaluate("() => document.body.scrollHeight")
        rounds = 0
        while rounds < max_rounds:
            rounds += 1
            await page.evaluate(f"window.scrollBy(0, {step});")
            await page.wait_for_timeout(wait_ms)
            new_height = await page.evaluate("() => document.body.scrollHeight")
            if new_height == last_height:
                await page.evaluate("window.scrollBy(0, 50);")
                await page.wait_for_timeout(wait_ms)
                new_height = await page.evaluate("() => document.body.scrollHeight")
                if new_height == last_height:
                    break
            last_height = new_height
        print("ℹ Scrolled page to load dynamic content.")
    except Exception as e:
        print(f"❌ Failed to scroll: {e}")

def clean_profile_url(u: str) -> str:
    """Remove tracking query params, force https, keep only /in/... path."""
    try:
        parsed = urlparse(u)
        if not parsed.netloc:
            u = urljoin("https://www.linkedin.com", u)
            parsed = urlparse(u)
        path = parsed.path
        if "/in/" in path:
            if not path.endswith("/"):
                path = path + "/"
            clean = urlunparse(("https", "www.linkedin.com", path, "", "", ""))
            return clean
        return u
    except Exception:
        return u

# -----------------------
# Browser setup
# -----------------------
async def setup_browser(playwright):
    browser = await playwright.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--window-size=1920,1080",
            "--disable-dev-shm-usage"
        ]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768}
    )
    page = await context.new_page()

    if cookies_path.exists():
        try:
            cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)
            print("✅ Loaded cookies from file.")
        except Exception as e:
            print(f"❌ Failed to load cookies: {e}")

    try:
        await page.goto("https://www.linkedin.com/feed/", timeout=90000)
        await page.wait_for_load_state("domcontentloaded")
        print("✅ LinkedIn feed loaded successfully.")
    except Exception:
        print("❌ Failed to load LinkedIn feed.")

    if "/login" in page.url or "challenge" in page.url:
        print("👉 Please log in manually in the opened browser window...")
        ask_question("🔑 Press Enter after login...")
        cookies = await context.cookies()
        cookies_path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        print("💾 Login session saved!")

    return browser, context, page

# -----------------------
# Scrape Education
# -----------------------
async def scrape_education(page, profile_url):
    try:
        base_url = clean_profile_url(profile_url)
        if "/in/" not in base_url:
            return ""
        username = base_url.split("/in/")[1].split("/")[0]
        education_url = f"https://www.linkedin.com/in/{username}/details/education/"

        print(f"🎓 Scraping education from: {education_url}")
        await page.goto(education_url, timeout=90000)
        await page.wait_for_timeout(4000)
        await auto_scroll(page, step=700, max_rounds=15, wait_ms=1200)
        await page.wait_for_timeout(2500)

        education = await page.evaluate(r"""() => {
            let collegeName = "";
            
            const eduItems = document.querySelectorAll('li.pvs-list__paged-list-item');
            
            for (const item of eduItems) {
                try {
                    const schoolNameEl = item.querySelector('.hoverable-link-text.t-bold span[aria-hidden="true"]');
                    if (schoolNameEl) {
                        const schoolText = schoolNameEl.innerText.trim();
                        
                        if (schoolText && 
                            schoolText.length > 5 && 
                            (schoolText.toLowerCase().includes('university') || 
                             schoolText.toLowerCase().includes('college') || 
                             schoolText.toLowerCase().includes('institute') ||
                             schoolText.includes('IIT') ||
                             schoolText.includes('NIT') ||
                             schoolText.includes('IIIT') ||
                             schoolText.includes('BITS') ||
                             schoolText.toLowerCase().includes('school')) &&
                            !schoolText.toLowerCase().includes('company') &&
                            !schoolText.toLowerCase().includes('pvt') &&
                            !schoolText.toLowerCase().includes('ltd') &&
                            !schoolText.toLowerCase().includes('technologies') &&
                            !schoolText.toLowerCase().includes('solutions')) {
                            
                            collegeName = schoolText;
                            break;
                        }
                    }
                } catch (e) {
                    continue;
                }
            }
            
            return collegeName || "";
        }""")

        return education

    except Exception as e:
        print(f"❌ Failed to scrape education for {profile_url}: {e}")
        return ""

# -----------------------
# Scrape Skills
# -----------------------
async def scrape_skills(page, profile_url):
    try:
        base_url = clean_profile_url(profile_url)
        if "/in/" not in base_url:
            return []
        username = base_url.split("/in/")[1].split("/")[0]
        skills_url = f"https://www.linkedin.com/in/{username}/details/skills/"

        print(f"🔍 Scraping skills from: {skills_url}")
        await page.goto(skills_url, timeout=90000)
        await page.wait_for_timeout(4000)
        await auto_scroll(page, step=700, max_rounds=20, wait_ms=1200)
        await page.wait_for_timeout(3000)

        skills = await page.evaluate(r"""() => {
            const skillsList = [];
            const seenSkills = new Set();
            
            const skillItems = document.querySelectorAll('li.pvs-list__paged-list-item');
            
            skillItems.forEach((item) => {
                try {
                    const skillNameEl = item.querySelector('.hoverable-link-text.t-bold span[aria-hidden="true"]');
                    if (skillNameEl) {
                        const skillText = skillNameEl.innerText.trim();
                        
                        if (skillText && 
                            skillText.length > 1 && 
                            skillText.length < 50 &&
                            !skillText.match(/^\d+/) &&
                            !skillText.includes('experience') &&
                            !skillText.includes('company') &&
                            !skillText.includes('at ') &&
                            !skillText.includes(' at ') &&
                            !skillText.includes('|') &&
                            !skillText.includes('endorsement') &&
                            !skillText.includes('connection') &&
                            !skillText.toLowerCase().includes('passed') &&
                            !skillText.toLowerCase().includes('linkedin') &&
                            !skillText.toLowerCase().includes('skill assessment') &&
                            skillText !== '·') {
                            
                            if (!seenSkills.has(skillText.toLowerCase())) {
                                skillsList.push(skillText);
                                seenSkills.add(skillText.toLowerCase());
                            }
                        }
                    }
                } catch (e) {
                    // Continue if there's an error with this item
                }
            });

            return skillsList;
        }""")

        return skills

    except Exception as e:
        print(f"❌ Failed to scrape skills for {profile_url}: {e}")
        return []

# -----------------------
# Scrape Experience
# -----------------------
async def scrape_experience(page, profile_url):
    try:
        base_url = clean_profile_url(profile_url)
        if "/in/" not in base_url:
            return {
                "experiences": [],
                "currentCompany": "N/A",
                "currentTitle": "N/A",
                "totalExperience": "N/A"
            }
        username = base_url.split("/in/")[1].split("/")[0]
        experience_url = f"https://www.linkedin.com/in/{username}/details/experience/"

        print(f"🔍 Scraping experience from: {experience_url}")
        await page.goto(experience_url, timeout=90000)
        await page.wait_for_timeout(4000)
        await auto_scroll(page, step=700, max_rounds=20, wait_ms=1200)
        await page.wait_for_timeout(3000)

        experience_data = await page.evaluate(r"""() => {
            const experiences = [];
            let currentCompany = "N/A";
            let currentTitle = "N/A";
            let totalExperience = "N/A";

            const experienceItems = document.querySelectorAll('li.pvs-list__paged-list-item');
            
            experienceItems.forEach((item) => {
                try {
                    let title = "N/A";
                    let company = "N/A";
                    let duration = "N/A";
                    let employmentType = "";
                    
                    const titleSelectors = [
                        'div.display-flex.align-items-center span[aria-hidden="true"]',
                        'div.hoverable-link-text.t-bold span[aria-hidden="true"]',
                        '.pvs-entity__summary-info .hoverable-link-text span[aria-hidden="true"]',
                        'a[data-field*="experience"] span[aria-hidden="true"]',
                        '.t-bold span[aria-hidden="true"]'
                    ];
                    
                    for (const selector of titleSelectors) {
                        const titleEl = item.querySelector(selector);
                        if (titleEl && titleEl.textContent && titleEl.textContent.trim()) {
                            const titleText = titleEl.textContent.trim();
                            if (!titleText.match(/\d+\s*(yr|mo|year|month)/i) && 
                                titleText.length < 100 && 
                                !titleText.includes('·')) {
                                title = titleText;
                                break;
                            }
                        }
                    }
                    
                    const companySelectors = [
                        '.pvs-entity__sub-components .hoverable-link-text span[aria-hidden="true"]',
                        '.t-14.t-normal span[aria-hidden="true"]',
                        '.pvs-entity__summary-info .t-14 span[aria-hidden="true"]'
                    ];
                    
                    for (const selector of companySelectors) {
                        const companyEl = item.querySelector(selector);
                        if (companyEl && companyEl.textContent && companyEl.textContent.trim()) {
                            const companyText = companyEl.textContent.trim();
                            if (!companyText.match(/Full-time|Part-time|Contract|Internship|Freelance|Self-employed|Temporary|\d+\s*(yr|mo)/i) &&
                                !companyText.includes('·') &&
                                companyText.length > 2) {
                                company = companyText;
                                break;
                            }
                        }
                    }
                    
                    const durationSelectors = [
                        '.pvs-entity__caption-wrapper',
                        '.t-12.t-normal span[aria-hidden="true"]',
                        '.pvs-entity__sub-components .t-12 span[aria-hidden="true"]'
                    ];
                    
                    for (const selector of durationSelectors) {
                        const durationEl = item.querySelector(selector);
                        if (durationEl && durationEl.textContent && durationEl.textContent.trim()) {
                            const durationText = durationEl.textContent.trim();
                            if (durationText.match(/\d+\s*(yr|mo|year|month)|Present|Current/i)) {
                                duration = durationText;
                                break;
                            }
                        }
                    }
                    
                    const subComponents = item.querySelector('.pvs-entity__sub-components');
                    if (subComponents) {
                        const companyNameEl = item.querySelector('.hoverable-link-text.t-bold span[aria-hidden="true"]');
                        const companyName = companyNameEl ? companyNameEl.textContent.trim() : "N/A";
                        
                        const positions = subComponents.querySelectorAll('li.pvs-list__paged-list-item');
                        positions.forEach(position => {
                            try {
                                const posTitle = position.querySelector('.hoverable-link-text.t-bold span[aria-hidden="true"]');
                                const posDuration = position.querySelector('.pvs-entity__caption-wrapper');
                                const posType = position.querySelector('.t-14.t-normal span[aria-hidden="true"]');
                                
                                experiences.push({
                                    company: companyName,
                                    title: posTitle ? posTitle.textContent.trim() : "N/A",
                                    duration: posDuration ? posDuration.textContent.trim() : "N/A",
                                    employmentType: posType ? posType.textContent.trim() : ""
                                });
                            } catch (e) {
                                console.log('Error parsing position:', e);
                            }
                        });
                    } else {
                        if (title !== "N/A" || company !== "N/A") {
                            experiences.push({
                                company: company,
                                title: title,
                                duration: duration,
                                employmentType: employmentType
                            });
                        }
                    }
                    
                } catch (e) {
                    console.log('Error parsing experience item:', e);
                }
            });

            const uniqueExperiences = [];
            const seen = new Set();
            
            experiences.forEach(exp => {
                const key = `${exp.company}-${exp.title}-${exp.duration}`;
                if (!seen.has(key) && exp.title !== "N/A" && exp.company !== "N/A") {
                    seen.add(key);
                    uniqueExperiences.push(exp);
                }
            });

            for (const exp of uniqueExperiences) {
                if (exp.duration && /Present|Current/i.test(exp.duration)) {
                    currentCompany = exp.company;
                    currentTitle = exp.title;
                    break;
                }
            }
            
            if (currentCompany === "N/A" && uniqueExperiences.length > 0) {
                currentCompany = uniqueExperiences[0].company;
                currentTitle = uniqueExperiences[0].title;
            }

            let totalYears = 0;
            let totalMonths = 0;
            
            uniqueExperiences.forEach(exp => {
                if (exp.duration) {
                    const yearMatch = exp.duration.match(/(\d+)\s*(yr|year)s?/i);
                    const monthMatch = exp.duration.match(/(\d+)\s*(mo|month)s?/i);
                    
                    if (yearMatch) {
                        totalYears += parseInt(yearMatch[1]);
                    }
                    if (monthMatch) {
                        totalMonths += parseInt(monthMatch[1]);
                    }
                }
            });
            
            totalYears += Math.floor(totalMonths / 12);
            totalMonths = totalMonths % 12;
            
            if (totalYears > 0 || totalMonths > 0) {
                totalExperience = `${totalYears} yrs ${totalMonths} mos`;
            }

            return {
                experiences: uniqueExperiences,
                currentCompany: currentCompany,
                currentTitle: currentTitle,
                totalExperience: totalExperience
            };
        }""")

        return experience_data

    except Exception as e:
        print(f"❌ Failed to scrape experience for {profile_url}: {e}")
        return {
            "experiences": [],
            "currentCompany": "N/A",
            "currentTitle": "N/A",
            "totalExperience": "N/A"
        }

# -----------------------
# Scrape Profile
# -----------------------
async def scrape_profile(page, profile_url):
    try:
        url = clean_profile_url(profile_url)
        await page.goto(url, timeout=90000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_selector("h1", timeout=15000)
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        await page.wait_for_timeout(4000)

        basic_data = await page.evaluate(r"""() => {
            const getText = (selectors) => {
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.trim()) return el.innerText.trim();
                }
                return "N/A";
            };

            const name = getText([
                "h1.inline.t-24.v-align-middle.break-words",
                "h1.text-heading-xlarge",
                "h1"
            ]);
            const title = getText([
                "div.text-body-medium.break-words",
                "div.text-body-medium",
                ".mt1.t-18.t-black.t-normal.break-words"
            ]);
            const location = getText([
                "span.text-body-small.inline.t-black--light.break-words",
                "span.text-body-small"
            ]);

            return {
                name,
                title,
                location
            };
        }""")

        education_data = await scrape_education(page, url)
        experience_data = await scrape_experience(page, url)
        skills_data = await scrape_skills(page, url)

        experience_details = []
        for exp in (experience_data.get("experiences") or []):
            detail = f"{exp.get('company','N/A')} | {exp.get('title','N/A')} | {exp.get('duration','N/A')}"
            et = exp.get('employmentType')
            if et:
                detail += f" | {et}"
            experience_details.append(detail)
        experience_details_str = " || ".join(experience_details[:5])

        skills_str = " | ".join(skills_data) if skills_data else "N/A"

        def clean_na(val):
            return "" if val == "N/A" else val
            
        result = {
            "name": clean_na(basic_data.get("name", "N/A")),
            "title": basic_data.get("title", "N/A"),
            "location": clean_na(basic_data.get("location", "N/A")),
            "education": education_data,
            "url": url,
            "total_experience": clean_na(experience_data.get("totalExperience", "N/A")),
            "experience_details": clean_na(experience_details_str),
            "skills": clean_na(skills_str)
        }
        
        print(f"✅ Scraped {url}: {result['name']} - {result['title']}")
            
        return result

    except Exception as e:
        print(f"❌ Failed to scrape {profile_url}: {e}")
        return {
            "name": "N/A", "title": "N/A", "location": "N/A",
            "education": "N/A", "url": clean_profile_url(profile_url),
            "total_experience": "N/A", "experience_details": "N/A",
            "skills": "N/A"
        }

# -----------------------
# Collect Profile URLs from LinkedIn Search Results - MODIFIED FOR SEARCH RESULTS
# -----------------------
async def collect_search_profile_urls(page, search_url, limit):
    profile_urls = set()
    print(f"🔍 Starting to collect {limit} profiles from search results: {search_url}")

    await page.goto(search_url, timeout=90000)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(5000)

    max_attempts = 50
    attempt = 0
    no_new_profiles_count = 0
    
    while attempt < max_attempts and len(profile_urls) < limit:
        attempt += 1
        previous_count = len(profile_urls)
        
        print(f"🔄 Collection attempt {attempt}/{max_attempts} - Profiles found: {len(profile_urls)}")
        
        await auto_scroll(page, step=1200, max_rounds=20, wait_ms=1500)
        await page.wait_for_timeout(4000)

        # LinkedIn Search Results - Next Page Navigation
        try:
            next_button_selectors = [
                "button[aria-label='Next']",
                "button[aria-label='next']",
                ".artdeco-pagination__button--next",
                "button.artdeco-pagination__button--next:not([disabled])",
                "button:has-text('Next')",
                "li.artdeco-pagination__indicator--number + li button",
                ".artdeco-pagination__button.artdeco-pagination__button--next:not([disabled])"
            ]
            
            for selector in next_button_selectors:
                try:
                    next_btn = await page.query_selector(selector)
                    if next_btn:
                        is_disabled = await next_btn.get_attribute('disabled')
                        is_visible = await next_btn.is_visible()
                        if not is_disabled and is_visible:
                            print("➡️ Found and clicking Next button...")
                            await next_btn.click()
                            await page.wait_for_timeout(6000)
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # Collect profile URLs from LinkedIn search results
        new_urls = await page.evaluate(r"""() => {
            const profileUrls = [];
            
            // LinkedIn search results have specific structure
            // Look for profile links in search result cards
            const searchResults = document.querySelectorAll('.reusable-search__result-container, .entity-result, .search-result, .search-result__info, .search-entity-card');
            
            searchResults.forEach(result => {
                // Look for profile links within each result
                const profileLinks = result.querySelectorAll("a[href*='/in/']");
                profileLinks.forEach(link => {
                    const href = link.href || link.getAttribute("href") || "";
                    if (href && href.includes("/in/") && 
                        !href.includes("/miniProfile/") && 
                        !href.includes("/company/") &&
                        !href.includes("/school/") &&
                        !href.includes("/feed/") &&
                        !href.includes("/posts/") &&
                        !href.includes("/activity/")) {
                        
                        const cleanUrl = href.split('?')[0];
                        profileUrls.push(cleanUrl);
                    }
                });
            });

            // Additional fallback - look for any profile links on page
            const allProfileLinks = document.querySelectorAll("a[href*='/in/']");
            allProfileLinks.forEach(link => {
                const href = link.href || link.getAttribute("href") || "";
                if (href && href.includes("/in/") && 
                    !href.includes("/miniProfile/") && 
                    !href.includes("/company/") &&
                    !href.includes("/school/") &&
                    !href.includes("/feed/") &&
                    !href.includes("/posts/") &&
                    !href.includes("/activity/")) {
                    
                    const cleanUrl = href.split('?')[0];
                    profileUrls.push(cleanUrl);
                }
            });
            
            // Remove duplicates
            return [...new Set(profileUrls)];
        }""")

        for url in new_urls:
            if url:
                profile_urls.add(url)

        new_profiles_found = len(profile_urls) - previous_count
        print(f"📊 Found {new_profiles_found} new profiles. Total profiles: {len(profile_urls)}")

        if new_profiles_found == 0:
            no_new_profiles_count += 1
        else:
            no_new_profiles_count = 0

        if no_new_profiles_count >= 8:
            print("🔄 No new profiles found in recent attempts. Trying different scroll pattern...")
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(4000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(5000)
            no_new_profiles_count = 0

        if len(profile_urls) >= limit:
            print(f"✅ Collected enough profiles: {len(profile_urls)}")
            break

        await delay(4000 + random.randint(3000, 6000))

    final_list = list(profile_urls)[:limit]
    print(f"🎯 Final collection: {len(final_list)} profiles")
    
    return final_list

# -----------------------
# Main execution function - MODIFIED FOR SEARCH RESULTS
# -----------------------
async def main():
    async with async_playwright() as p:
        browser, context, page = await setup_browser(p)

        # Ask for LinkedIn search results URL
        print("📝 Please provide the LinkedIn search results URL for Engineering professionals")
        print("Example: https://www.linkedin.com/search/results/people/?keywords=software%20engineer...")
        
        search_url = ask_question("🔗 Enter the LinkedIn search results URL: ").strip()
        if not search_url:
            print("❌ URL is required. Exiting.")
            await browser.close()
            return

        # Validate URL format
        if "linkedin.com/search/results/people" not in search_url:
            print("❌ Please provide a valid LinkedIn people search results URL")
            await browser.close()
            return

        try:
            limit = int(ask_question("🔢 How many profiles to scrape? (default: 10): ").strip() or "10")
        except Exception:
            limit = 10

        print(f"🎯 Target URL: {search_url}")

        # Collect profile URLs from the search results page
        urls = await collect_search_profile_urls(page, search_url, limit)
        
        if not urls:
            print("❌ No profile URLs found. Please check the URL or search filters.")
            await browser.close()
            return

        print(f"🎯 Starting to scrape {len(urls)} profiles...")
        results = []
        
        for i, url in enumerate(urls, 1):
            print(f"\n🔍 [{i}/{len(urls)}] Scraping: {url}")
            try:
                profile_data = await scrape_profile(page, url)
                results.append(profile_data)
                
                if i < len(urls):
                    delay_time = 5000 + random.randint(2000, 8000)
                    print(f"⏳ Waiting {delay_time/1000:.1f}s before next profile...")
                    await delay(delay_time)
                    
            except Exception as e:
                print(f"❌ Failed to scrape profile {url}: {e}")
                results.append({
                    "name": "Failed to scrape", 
                    "title": "N/A", 
                    "location": "N/A",
                    "education": "N/A", 
                    "url": url,
                    "total_experience": "N/A", 
                    "experience_details": "N/A",
                    "skills": "N/A"
                })

        # Save results to CSV
        if results:
            save_to_csv(results)
            open_excel(output_csv)
            
            print(f"\n🎉 LinkedIn Engineering Scraping completed!")
            print(f"📊 Total profiles scraped: {len(results)}")
            print(f"📁 Results saved to: {output_csv}")
        else:
            print("❌ No data to save.")

        await browser.close()

# Entry point
# -----------------------