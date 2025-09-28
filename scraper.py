

from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from io import BytesIO
import pytesseract
import google.generativeai as genai
import json
import logging
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import base64
from datetime import datetime
import os

pytesseract.pytesseract.tesseract_cmd = r'C:/Program Files/Tesseract-OCR/tesseract.exe'

# -------------------
# Logging setup
# -------------------
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# -------------------
# Load environment variables
# -------------------
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-flash")

CAPTCHA_API_KEY = "e0789a56011da02cbd3968ef6f0b227b"

# -------------------
# CAPTCHA Solver
# -------------------
class CaptchaSolver:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"

    def solve_image_captcha(self, image_base64):
        try:
            submit_url = f"{self.base_url}/in.php"
            submit_data = {'key': self.api_key, 'method': 'base64', 'body': image_base64, 'json': 1}
            submit_response = requests.post(submit_url, data=submit_data, timeout=7)
            submit_result = submit_response.json()
            if submit_result.get('status') != 1:
                raise Exception(f"Failed to submit CAPTCHA: {submit_result.get('error_text')}")
            captcha_id = submit_result.get('request')

            # Poll for result
            result_url = f"{self.base_url}/res.php"
            for _ in range(20):
                time.sleep(1)
                result_params = {'key': self.api_key, 'action': 'get', 'id': captcha_id, 'json': 1}
                result_response = requests.get(result_url, params=result_params, timeout=8)
                result_data = result_response.json()
                if result_data.get('status') == 1:
                    return result_data.get('request')
            raise Exception("CAPTCHA solving timed out")
        except Exception as e:
            logging.error(f"CAPTCHA solving error: {e}")
            return None

    def get_image_base64_from_element(self, driver, image_element):
        try:
            src = image_element.get_attribute('src')
            if src.startswith('data:image'):
                return src.split(',')[1]
            response = requests.get(src)
            return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            logging.warning(f"Error getting image base64: {e}")
            return None

# -------------------
# Utility Functions
# -------------------
def wait_for_manual_captcha(driver, captcha_input, max_wait_time=30):
    logging.info("Waiting for manual CAPTCHA entry...")
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        try:
            value = captcha_input.get_attribute('value')
            if value and value.strip():
                logging.info("Manual CAPTCHA entry detected!")
                return True
        except:
            pass
        time.sleep(1)
    logging.warning("Timeout reached for manual CAPTCHA entry")
    return False

def preprocess_image(image: Image.Image) -> Image.Image:
    try:
        image = ImageOps.grayscale(image)
        image = image.resize((image.width * 2, image.height * 2))
        return image
    except Exception as e:
        logging.warning(f"Image preprocessing failed: {e}")
        return image

def scrape_text_and_images(url: str) -> str:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Error fetching page {url}: {e}")
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    full_text = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all())
    images = soup.find_all("img")
    for img in images:
        img_url = img.get("src")
        if not img_url:
            continue
        img_url = urljoin(url, img_url)
        try:
            img_response = requests.get(img_url, timeout=10)
            if "image" not in img_response.headers.get("Content-Type", ""):
                continue
            image = Image.open(BytesIO(img_response.content))
            image = preprocess_image(image)
            text = pytesseract.image_to_string(image)
            logging.info(f"OCR from image at {img_url} extracted text length: {len(text.strip())}")
            full_text += " " + text
        except Exception as e:
            logging.warning(f"Skipping image {img_url}: {e}")
            continue
    return full_text

def extract_license_with_llm(url: str, max_retries: int = 2) -> dict:
    combined_text = scrape_text_and_images(url)
    prompt = (
        "Extract license information from the following content. Return ONLY valid JSON. "
        "Fields: license_number, shelf_life, expiry_date, manufacturer_name. "
        "Text:\n" + combined_text
    )
    for attempt in range(max_retries):
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start >= 0 and json_end > 0:
            json_str = response_text[json_start:json_end]
            try:
                data = json.loads(json_str)
                return data
            except json.JSONDecodeError as e:
                logging.error(f"JSON parsing error: {e}")
    return {"error": "Failed to get valid JSON", "raw_response": response_text}

def save_results_to_file(data, filename=None):
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"foscos_results_{timestamp}.json"
    results_folder = os.path.join(os.getcwd(), "results")
    os.makedirs(results_folder, exist_ok=True)
    filepath = os.path.join(results_folder, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logging.info(f"Results saved to: {filepath}")
    except Exception as e:
        logging.error(f"Failed to save results: {e}")
    return filepath

# -------------------
# FoSCoS Automation
# -------------------
def automate_foscos_form(license_number: str):
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=options)
    captcha_solver = CaptchaSolver(CAPTCHA_API_KEY)
    wait = WebDriverWait(driver, 10)

    foscos_data = {"license_search_results": [], "product_details": None, "search_successful": False, "products_extracted": False}

    try:
        driver.get("https://foscos.fssai.gov.in")
        time.sleep(3)

        # Click FBO Search tab
        try:
            fbo_tab = driver.find_element(By.XPATH, "//b[text()='FBO Search']/parent::a")
            driver.execute_script("arguments[0].click();", fbo_tab)
            time.sleep(2)
        except:
            logging.warning("FBO Search tab not found")

        # License input
        license_input = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[contains(@placeholder, 'License')]")))
        license_input.clear()
        license_input.send_keys(license_number)

        # CAPTCHA handling
        captcha_image = driver.find_element(By.XPATH, "//img[contains(@alt, 'Captcha')]")
        captcha_input = driver.find_element(By.XPATH, "//input[contains(@placeholder, 'Captcha')]")
        image_base64 = captcha_solver.get_image_base64_from_element(driver, captcha_image)
        captcha_solution = captcha_solver.solve_image_captcha(image_base64)
        if captcha_solution:
            captcha_input.clear()
            captcha_input.send_keys(captcha_solution)
        else:
            wait_for_manual_captcha(driver, captcha_input)

        # Click Search
        search_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Search')]")
        driver.execute_script("arguments[0].click();", search_button)
        time.sleep(3)

        # Extract table data
        table = driver.find_element(By.CSS_SELECTOR, "table.responsive-table, table#data-table-simple, table.dataTable")
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 6:
                foscos_data["license_search_results"].append({
                    "sno": cells[0].text.strip(),
                    "company_name": cells[1].text.strip(),
                    "premises_address": cells[2].text.strip(),
                    "license_number": cells[3].text.strip(),
                    "license_type": cells[4].text.strip(),
                    "status": cells[5].text.strip(),
                    "view_products_available": "View Products" in row.text
                })

        foscos_data["search_successful"] = len(foscos_data["license_search_results"]) > 0

        # Extract product details if "View Products" exists
        try:
            view_products = driver.find_element(By.XPATH, "//a[contains(text(), 'View Products')]")
            driver.execute_script("arguments[0].click();", view_products)
            time.sleep(2)
            page_content = driver.page_source
            foscos_data["product_details"] = extract_product_details_with_llm(page_content)
            foscos_data["products_extracted"] = True
        except:
            logging.info("No 'View Products' button found")

        final_data = {
            "extraction_timestamp": datetime.now().isoformat(),
            "source_license_number": license_number,
            "search_results": foscos_data["license_search_results"],
            "product_details": foscos_data["product_details"],
            "summary": {
                "search_successful": foscos_data["search_successful"],
                "products_extracted": foscos_data["products_extracted"],
                "total_records_found": len(foscos_data["license_search_results"])
            },
            "page_url": driver.current_url
        }

        save_results_to_file(final_data, filename="foscos_result.json")
        return final_data

    except Exception as e:
        logging.error(f"Error during FoSCoS automation: {e}")
        save_results_to_file(foscos_data, filename="foscos_partial.json")
        return foscos_data
    finally:
        driver.quit()

# -------------------
# Helper for extracting product details using LLM
# -------------------
def extract_product_details_with_llm(page_content):
    prompt = (
        "Extract all available product/license details from the following content. "
        "Return ONLY a valid JSON object. Include fields like company_name, license_number, license_type, "
        "status, validity, address, products, manufacturing_details. If missing, use null.\n"
        "Content:\n" + page_content
    )
    response = model.generate_content(prompt)
    response_text = response.text.strip()
    json_start = response_text.find('{')
    json_end = response_text.rfind('}') + 1
    if json_start >= 0 and json_end > 0:
        try:
            return json.loads(response_text[json_start:json_end])
        except:
            return {"error": "Failed to parse JSON from LLM"}
    return {"error": "No JSON found in LLM response"}

# -------------------
# Main Execution
# -------------------
if __name__ == "__main__":
    product_url = "https://www.avvatarindia.com/product/alpha-whey-belgian-chocolate-flavour-2-kg"
    logging.info(f"Extracting license info from {product_url} ...")
    result = extract_license_with_llm(product_url)

    # Save initial extraction always
    save_results_to_file(result, filename="llm_extraction.json")

    license_number = result.get("license_number")
    if license_number:
        logging.info(f"License number extracted: {license_number}")
        foscos_result = automate_foscos_form(license_number)
        logging.info("Final FoSCoS Result saved.")
    else:
        logging.warning("License number could not be extracted.")
        