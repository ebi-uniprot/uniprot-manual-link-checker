#!/usr/bin/env python3
from glob import glob
import os
from urllib.parse import unquote, urlparse
from ftplib import FTP
from bs4 import BeautifulSoup
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.keys import Keys
from fake_useragent import UserAgent
import markdown

# Use this to fake a valid user agent for requests
ua = UserAgent()
headers = {"User-Agent": ua.Chrome}

options = Options()
options.headless = True

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()), options=options
)

DEAD_LINKS_FILE = "./dead-links.tsv"
DEAD_ANCHORS_FILE = "./dead-anchors.tsv"

UNIPROT_BETA_HELP_URL = "https://beta.uniprot.org/help"
UNIPROT_ORG_URL = "www.uniprot.org"
UNIPROT_BETA_URL = "beta.uniprot.org"
UNIPROT_ORG_KB_PATH = "/uniprot"
UNIPROT_BETA_KB_PATH = "/uniprotkb"

TIMEOUT = 5


def get_beta_help_url(help_file):
    basename = os.path.basename(help_file)
    filename, _ = os.path.splitext(basename)
    return os.path.join(UNIPROT_BETA_HELP_URL, filename)


def does_page_exist(url):
    try:
        response = requests.get(url, headers=headers, timeout=10)
    except:
        return False
    return response.ok


def is_anchor_in_page(anchor):
    try:
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, anchor))
        )
    except:
        return False
    return len(driver.find_elements(by=By.ID, value=anchor)) > 0


def is_error():
    error_xpath = (
        "//*[@class='message--failure' or @class='error-page-container__art-work']"
    )
    try:
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, error_xpath))
        )
    except:
        return False
    return driver.find_elements(by=By.XPATH, value=error_xpath), None


def is_uniprot_beta_url_ok(parsed):
    url = parsed.geturl()
    assert UNIPROT_BETA_URL in url
    driver.get(url)
    not_found_class_names = ["message--failure", "error-page-container__art-work"]
    for class_name in not_found_class_names:
        if driver.find_elements(by=By.CLASS_NAME, value=class_name):
            return False, None
    if parsed.fragment:
        return True, is_anchor_in_page(unquote(parsed.fragment))

    return True, None


def is_ftp_url_ok(parsed):
    try:
        ftp = FTP(parsed.netloc)
        ftp.login()
        path = unquote(parsed.path)
    except:
        return False
    try:
        ftp.cwd(path)
        return True
    except:
        try:
            ftp.size(path)
            return True
        except:
            return False


def is_url_ok(url):
    parsed = urlparse(url)
    if parsed.scheme == "ftp":
        return is_ftp_url_ok(parsed), None
    paths = os.path.split(parsed.path)

    # If nothing as hostname assume this to be uniprot
    if parsed.hostname is None:
        parsed = parsed._replace(netloc=UNIPROT_ORG_URL)

    # Check if this is uniprot.org
    if parsed.hostname == UNIPROT_ORG_URL:
        # Always use HTTPS
        parsed = parsed._replace(scheme="https")

        # Check if this uniprot(kb) and if so replace path
        if paths[0].lower() == UNIPROT_ORG_KB_PATH:
            paths = [UNIPROT_BETA_KB_PATH, *paths[1:]]
            parsed = parsed._replace(path=os.path.join(*paths))

        # /manual redirects to /help now
        elif paths[0] == "/manual":
            paths = ["/help/", *paths[1:]]
            parsed = parsed._replace(path=os.path.join(*paths))

        # Check that the corresponding beta page exists
        beta_parsed = parsed._replace(netloc=UNIPROT_BETA_URL)
        ok, anchor_found = is_uniprot_beta_url_ok(beta_parsed)
        return ok, anchor_found
    else:
        # Well this isn't ideal but not sure how else to handle this
        # as if the resource is a SPA I won't know what to look for
        # the resource not being able to be accessed
        return does_page_exist(url), None


def check_and_standardize_all_links(soup):
    _dead_links = []
    _dead_anchors = []
    for el in soup.find_all("a"):
        if "href" not in el.attrs:
            _dead_links.append(f'Anchor tag: {",".join(el.attrs.values())}')
            continue
        url = el.attrs["href"]
        ok, anchor_found = is_url_ok(url)
        if ok is not None and not ok:
            _dead_links.append(url)
        if anchor_found is not None and not anchor_found:
            _dead_anchors.append(url)
    return set(_dead_links), set(_dead_anchors)


def remove_if_exists(path):
    if os.path.exists(path):
        os.remove(path)


if __name__ == "__main__":

    remove_if_exists(DEAD_ANCHORS_FILE)
    remove_if_exists(DEAD_LINKS_FILE)

    help_files = glob("./uniprot-manual/help/*.md")

    all_dead_links = []
    all_dead_anchors = []

    with open(DEAD_ANCHORS_FILE, "w") as af, open(DEAD_LINKS_FILE, "w") as lf:
        for i, help_file in enumerate(help_files):
            try:
                print(help_file)
                with open(help_file) as f:
                    md = f.read()
                html = markdown.markdown(md)
                soup = BeautifulSoup(html, features="html.parser")
                dead_links, dead_anchors = check_and_standardize_all_links(soup)
                beta_help_url = get_beta_help_url(help_file)
                for dead_link in dead_links:
                    print(f"{beta_help_url}\t{dead_link}", file=lf)
                    lf.flush()
                for dead_anchor in dead_anchors:
                    print(f"{beta_help_url}\t{dead_anchor}", file=af)
                    af.flush()
            except Exception as e:
                print(e)
