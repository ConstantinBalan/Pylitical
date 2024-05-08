from bs4 import BeautifulSoup
import requests
import ChatSummarize
from datetime import datetime
import multiprocessing
import sys
import time
import itertools


# This function will return a dictionary containing the urls of bills and resolutions
def create_bill_url_dict(parsable_html, base_url, title_names) -> dict:
    soup = BeautifulSoup(parsable_html, "html.parser")

    # The idea with this dictionary was to have the keys be the state of the bill, and the values be a list of the urls of the bills
    bill_url_dictionary = {
        "Introduced": [],
        "Passed by Chamber": [],
        "Enrolled": [],
        "Adopted": [],
    }

    # Loop through each section by the title of the section
    for name in title_names:
        # Assign the title object of the section to title_element
        title_element = soup.find("h3", text=name)

        # For the MI case, I think the next sibling is always table, but I put the cycle through siblings in anyway
        if title_element:
            table_element = title_element.find_next_sibling()

        if table_element:
            tbody = table_element.find("tbody")

            # Check if the tbody element exists, the get the href value from the <a> element and assign it to the dictionary
            if tbody:
                for table_row in tbody.find_all("tr"):
                    first_data_cell = table_row.find("td")

                    if first_data_cell and first_data_cell.find("a"):
                        href = first_data_cell.find("a")["href"]
                        bill_url_dictionary[name].append(base_url + href)

    print(bill_url_dictionary)
    return bill_url_dictionary


# This will get an html object from a specified url
def get_webpage_contents(url) -> str:
    response = requests.get(url)

    if response.status_code == 200:
        html_content = response.text
    else:
        print(f"Failed to fetch HTML from {url}. Status code: {response.status_code}")
    return html_content


# This ideally will return a dictionary of the HTML files that contain the actual contents of the bills
def get_list_of_bill_html_files(base_url, bill_dict, bill_status_string) -> dict:

    # This will be the return value
    bill_name_status_and_html_link_dict = {}
    bill_status_html_keywords = []

    match bill_status_string:
        case "Introduced":
            bill_status_html_keywords.append("Introduced")
        case "Passed by Chamber":
            bill_status_html_keywords.append("Passed by the House")
            bill_status_html_keywords.append("Passed by the Senate")
        case "Enrolled":
            bill_status_html_keywords.append("Concurred")
            bill_status_html_keywords.append("Enrolled")
        case "Adopted":
            bill_status_html_keywords.append("Adopted")
        case _:
            NameError(
                "The case check in get_list_of_bill_html_files wasn't able to match a string."
            )

    # This is for the bills/resolutions for the Introduced section
    for bill_url in bill_dict[bill_status_string]:
        # Retrieve HTML of bill web page
        bill_html = get_webpage_contents(bill_url)
        # Assign HTML to soup object
        soup = BeautifulSoup(bill_html, "html.parser")

        # Getting the name of the bill (this is gonna be weird if the text has hyperlinks inside of hrefs, but we'll figure that out later)
        bill_name_header = soup.find("h1", id="BillHeading")
        bill_name = bill_name_header.get_text()

        # Get the billDocuments div element, which contains all of the
        bill_documents_div = soup.find("div", class_="billDocuments")
        # print(bill_documents_div)
        if bill_documents_div:
            for bill_doc_row in bill_documents_div.find_all(
                "div", class_="bill_doc_row"
            ):
                is_current_state_html_doc = False
                # Conditional to check if this is the introduced bill version
                # TODO:Make this a function eventually or something
                text_div = bill_doc_row.find("div", class_="text")
                if text_div:
                    strong_text = text_div.find("strong")
                    if any(
                        element in strong_text.get_text()
                        for element in bill_status_html_keywords
                    ):
                        print(f"Found the {bill_status_string} bill")
                        bill_name_status_and_html_link_dict["Bill Status"] = (
                            bill_status_string
                        )
                        is_current_state_html_doc = True
                    else:
                        ValueError(
                            f"Could not find the keyword relating to {bill_status_string} for {bill_name}"
                        )

                # This will append the status of the bill and the .html link to the dictionary if the string accompanying the html doc matches up with the bill_status_string that is passed in
                # TODO: Potentially also turn this into a function
                # --------------------------------------------------------------
                if is_current_state_html_doc is True:
                    bill_doc_html_ele = bill_doc_row.find("div", class_="html")
                    bill_document_html_link = bill_doc_html_ele.find("a")["href"]
                    bill_document_full_link = base_url + bill_document_html_link
                    if bill_name in bill_name_status_and_html_link_dict:
                        bill_name_status_and_html_link_dict[bill_name].append(
                            bill_document_full_link
                        )
                    else:
                        bill_name_status_and_html_link_dict[bill_name] = [
                            bill_document_full_link
                        ]
                # --------------------------------------------------------------

    print(f"This is the {bill_status_string} dictionary")
    print(bill_name_status_and_html_link_dict)
    if not bill_name_status_and_html_link_dict:
        print(
            f"The {bill_status_string} dictionary is empty for the provided time range. Exiting process..."
        )
        sys.exit()
    return bill_name_status_and_html_link_dict


# Returns date interpolated url
def interpolate_url_with_date(daily_report_url, start_date, end_date):
    # Set the default to return the results for the day
    return_url = daily_report_url
    # Checks if both start and end date are empty, and if they are, returns the bare daily_report_url
    if not start_date and not end_date:
        return return_url

    # Errors out if the end_date is provided with no start_date
    if end_date and not start_date:
        SyntaxError(
            "ERROR - Passed in end_date but no start_date for the interpolate_url_with_date function."
        )

    start_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_date = datetime.strptime(end_date, "%Y-%m-%d")

    # Checks if the date ranges are valid
    if start_date < end_date:
        ValueError("ERROR - Start date is before end date.")
    elif start_date == end_date:
        ValueError("ERROR - Start date is the same as end date.")

    return_url = f"{daily_report_url}?dateFrom={start_date}&dateTo={end_date}"
    return return_url


def get_bill_summary(bill_html_dict):
    bill_status = bill_html_dict.get("Bill Status")
    print(f"The bill status of this dictionary is {bill_status}")
    # For each key in the dictionary, take the value
    # For the value, assign it to a soup object
    # For each soup object, getalltext
    # For all text, pass into summarize function
    for bill_key, bill_values in itertools.islice(bill_html_dict.items(), 1, None):
        print(f"Getting information for {bill_key}...")
        for bill_value in bill_values:
            current_bill_html = get_webpage_contents(bill_value)
            soup = BeautifulSoup(current_bill_html, "html.parser")
            all_bill_text = soup.get_text()
            summarized_bill = ChatSummarize.summarize_bill_info(
                bill_status, bill_key, all_bill_text
            )
            with open("page_text.txt", "a", encoding="utf-8") as file:
                file.write(str(summarized_bill))
                file.write("----------------------------------------------")
            time.sleep(10)


def process_task(base_url, bill_dict, status, queue):
    htmlDict = get_list_of_bill_html_files(base_url, bill_dict, status)
    queue.put(htmlDict)


def main():
    test()


def test():
    title_names = ["Introduced", "Passed by Chamber", "Enrolled", "Adopted"]
    base_url = "https://legislature.mi.gov"
    daily_report_url = "https://legislature.mi.gov/Bills/DailyReport"
    dail_rep_url = interpolate_url_with_date(
        daily_report_url, "2024-03-11", "2024-03-12"
    )
    html_object = get_webpage_contents(dail_rep_url)
    bill_dict = create_bill_url_dict(html_object, base_url, title_names)

    results_queue = multiprocessing.Queue()

    processes = []
    for status in title_names:
        process = multiprocessing.Process(
            target=process_task, args=(base_url, bill_dict, status, results_queue)
        )
        processes.append(process)
        process.start()

    for process in processes:
        process.join()

    while not results_queue.empty():
        htmlDict = results_queue.get()
        get_bill_summary(htmlDict)


if __name__ == "__main__":
    main()
