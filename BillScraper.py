from bs4 import BeautifulSoup
import requests
import ChatSummarize
from datetime import datetime
import multiprocessing
import sys
import time
import itertools


# This function will return a dictionary containing the urls of bills and resolutions
def create_bill_url_dict(parsableHTML, baseUrl, titleNames) -> dict:
    soup = BeautifulSoup(parsableHTML, "html.parser")

    # The idea with this dictionary was to have the keys be the state of the bill, and the values be a list of the urls of the bills
    billURLDictionary = {
        "Introduced": [],
        "Passed by Chamber": [],
        "Enrolled": [],
        "Adopted": [],
    }

    # Loop through each section by the title of the section
    for name in titleNames:
        # Assign the title object of the section to titleElement
        titleElement = soup.find("h3", text=name)

        # For the MI case, I think the next sibling is always table, but I put the cycle through siblings in anyway
        if titleElement:
            tableElement = titleElement.find_next_sibling()

        if tableElement:
            tbody = tableElement.find("tbody")

            # Check if the tbody element exists, the get the href value from the <a> element and assign it to the dictionary
            if tbody:
                for tablerow in tbody.find_all("tr"):
                    first_data_cell = tablerow.find("td")

                    if first_data_cell and first_data_cell.find("a"):
                        href = first_data_cell.find("a")["href"]
                        billURLDictionary[name].append(baseUrl + href)

    print(billURLDictionary)
    return billURLDictionary


# This will get an html object from a specified url
def get_webpage_contents(url) -> str:
    response = requests.get(url)

    if response.status_code == 200:
        html_content = response.text
    else:
        print(f"Failed to fetch HTML from {url}. Status code: {response.status_code}")
    return html_content


# This ideally will return a dictionary of the HTML files that contain the actual contents of the bills
def get_list_of_bill_html_files(baseUrl, billDict, billStatusString) -> dict:

    # This will be the return value
    billNameStatusAndHtmlLinkDict = {}
    billStatusHTMLKeyWords = []

    match billStatusString:
        case "Introduced":
            billStatusHTMLKeyWords.append("Introduced")
        case "Passed by Chamber":
            billStatusHTMLKeyWords.append("Passed by the House")
            billStatusHTMLKeyWords.append("Passed by the Senate")
        case "Enrolled":
            billStatusHTMLKeyWords.append("Concurred")
            billStatusHTMLKeyWords.append("Enrolled")
        case "Adopted":
            billStatusHTMLKeyWords.append("Adopted")
        case _:
            NameError(
                "The case check in get_list_of_bill_html_files wasn't able to match a string."
            )

    # This is for the bills/resolutions for the Introduced section
    for billUrl in billDict[billStatusString]:
        # Retrieve HTML of bill web page
        billHTML = get_webpage_contents(billUrl)
        # Assign HTML to soup object
        soup = BeautifulSoup(billHTML, "html.parser")

        # Getting the name of the bill (this is gonna be weird if the text has hyperlinks inside of hrefs, but we'll figure that out later)
        billNameHeader = soup.find("h1", id="BillHeading")
        billName = billNameHeader.get_text()

        # Get the billDocuments div element, which contains all of the
        billDocumentsDiv = soup.find("div", class_="billDocuments")
        # print(billDocumentsDiv)
        if billDocumentsDiv:
            for billDocRow in billDocumentsDiv.find_all("div", class_="billDocRow"):
                isCurrentStateHTMLDoc = False
                # Conditional to check if this is the introduced bill version
                # TODO:Make this a function eventually or something
                text_div = billDocRow.find("div", class_="text")
                if text_div:
                    strong_text = text_div.find("strong")
                    if any(
                        element in strong_text.get_text()
                        for element in billStatusHTMLKeyWords
                    ):
                        print(f"Found the {billStatusString} bill")
                        billNameStatusAndHtmlLinkDict["Bill Status"] = billStatusString
                        isCurrentStateHTMLDoc = True
                    else:
                        ValueError(
                            f"Could not find the keyword relating to {billStatusString} for {billName}"
                        )

                # This will append the status of the bill and the .html link to the dictionary if the string accompanying the html doc matches up with the billStatusString that is passed in
                # TODO: Potentially also turn this into a function
                # --------------------------------------------------------------
                if isCurrentStateHTMLDoc is True:
                    billDocHtmlEle = billDocRow.find("div", class_="html")
                    billDocumentHtmlLink = billDocHtmlEle.find("a")["href"]
                    billDocumentFullLink = baseUrl + billDocumentHtmlLink
                    if billName in billNameStatusAndHtmlLinkDict:
                        billNameStatusAndHtmlLinkDict[billName].append(
                            billDocumentFullLink
                        )
                    else:
                        billNameStatusAndHtmlLinkDict[billName] = [billDocumentFullLink]
                # --------------------------------------------------------------

    print(f"This is the {billStatusString} dictionary")
    print(billNameStatusAndHtmlLinkDict)
    if not billNameStatusAndHtmlLinkDict:
        print(
            f"The {billStatusString} dictionary is empty for the provided time range. Exiting process..."
        )
        sys.exit()
    return billNameStatusAndHtmlLinkDict


# Returns date interpolated url
def interpolate_url_with_date(dailyReportUrl, startDate, endDate):
    # Set the default to return the results for the day
    return_url = dailyReportUrl
    # Checks if both start and end date are empty, and if they are, returns the bare dailyReportUrl
    if not startDate and not endDate:
        return return_url

    # Errors out if the endDate is provided with no startDate
    if endDate and not startDate:
        SyntaxError(
            "ERROR - Passed in endDate but no startDate for the interpolate_url_with_date function."
        )

    start_date = datetime.strptime(startDate, "%Y-%m-%d")
    end_date = datetime.strptime(endDate, "%Y-%m-%d")

    # Checks if the date ranges are valid
    if start_date < end_date:
        ValueError("ERROR - Start date is before end date.")
    elif start_date == end_date:
        ValueError("ERROR - Start date is the same as end date.")

    return_url = f"{dailyReportUrl}?dateFrom={startDate}&dateTo={endDate}"
    return return_url


def get_bill_summary(billHTMLDict):
    billStatus = billHTMLDict.get("Bill Status")
    print(f"The bill status of this dictionary is {billStatus}")
    # For each key in the dictionary, take the value
    # For the value, assign it to a soup object
    # For each soup object, getalltext
    # For all text, pass into summarize function
    for billKey, billValues in itertools.islice(billHTMLDict.items(), 1, None):
        print(f"Getting information for {billKey}...")
        for billValue in billValues:
            currentBillHtml = get_webpage_contents(billValue)
            soup = BeautifulSoup(currentBillHtml, "html.parser")
            all_bill_text = soup.get_text()
            summarizedBill = ChatSummarize.summarize_bill_info(
                billStatus, billKey, all_bill_text
            )
            with open("page_text.txt", "a", encoding="utf-8") as file:
                file.write(str(summarizedBill))
                file.write("----------------------------------------------")
            time.sleep(10)


def process_task(base_url, billDict, status, queue):
    htmlDict = get_list_of_bill_html_files(base_url, billDict, status)
    queue.put(htmlDict)


def main():
    test()


def test():
    titleNames = ["Introduced", "Passed by Chamber", "Enrolled", "Adopted"]
    base_url = "https://legislature.mi.gov"
    daily_report_url = "https://legislature.mi.gov/Bills/DailyReport"
    dail_rep_url = interpolate_url_with_date(
        daily_report_url, "2024-03-11", "2024-03-12"
    )
    html_object = get_webpage_contents(dail_rep_url)
    billDict = create_bill_url_dict(html_object, base_url, titleNames)

    results_queue = multiprocessing.Queue()

    processes = []
    for status in titleNames:
        process = multiprocessing.Process(
            target=process_task, args=(base_url, billDict, status, results_queue)
        )
        processes.append(process)
        process.start()

    for process in processes:
        process.join()

    while not results_queue.empty():
        htmlDict = results_queue.get()
        # Do something with status and result, e.g., pass them to another function
        get_bill_summary(htmlDict)


if __name__ == "__main__":
    main()
