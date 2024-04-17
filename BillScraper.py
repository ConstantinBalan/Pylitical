from bs4 import BeautifulSoup
import requests
import ChatSummarize


def billsByDate(dateRange):
    print("Placeholder")


def billsByCategory(categoryName):
    print("Placeholder")


def main():
    print("Placeholder")


# This function will return a dictionary containing the urls of bills and resolutions
def createBillUrlDict(parsableHTML, baseUrl):
    soup = BeautifulSoup(parsableHTML, "html.parser")

    # The idea with this dictionary was to have the keys be the state of the bill, and the values be a list of the urls of the bills
    billURLDictionary = {
        "Introduced": [],
        "Passed by Chamber": [],
        "Enrolled": [],
        "Adopted": [],
    }

    titleNames = ["Introduced", "Passed by Chamber", "Enrolled", "Adopted"]

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
def getWebpageContents(url):
    response = requests.get(url)

    if response.status_code == 200:
        html_content = response.text
    else:
        print(f"Failed to fetch HTML from {url}. Status code: {response.status_code}")
    return html_content


# This ideally will return a dictionary of the HTML files that contain the actual contents of the bills
def getListOfBillHTMLFiles(baseUrl, billDict):

    # This will be the return value
    billNameStatusAndHtmlLinkDict = {}

    for introducedBillUrl in billDict["Introduced"]:
        # Retrieve HTML of bill web page
        introBillHTML = getWebpageContents(introducedBillUrl)
        # Assign HTML to soup object
        soup = BeautifulSoup(introBillHTML, "html.parser")

        # Getting the name of the bill (this is gonna be weird if the text has hyperlinks inside of hrefs, but we'll figure that out later)
        billNameHeader = soup.find("h1", id="BillHeading")
        billName = billNameHeader.get_text()

        # //*[@id="BillDocumentSection"]/div[2]/div[1]/div[3]/span[1]/strong

        # //*[@id="BillDocumentSection"]/div[2]/div[1]/div[3]/span[1]/strong
        # //*[@id="BillDocumentSection"]/div[2]/div[3]/div[3]/span[1]/strong
        # Get the billDocuments div element, which contains all of the
        billDocumentsDiv = soup.find("div", class_="billDocuments")
        # print(billDocumentsDiv)
        if billDocumentsDiv:
            for billDocRow in billDocumentsDiv.find_all("div", class_="billDocRow"):
                # print(   "------------------------this is billDocRow------------------------" )
                print(billDocRow)
                billDocHtmlEle = billDocRow.find("div", class_="html")
                # print(   "------------------------this is billDocHtmlEle------------------------"     )
                # print(billDocHtmlEle)
                billDocumentHtmlLink = billDocHtmlEle.find("a")["href"]
                billDocumentFullLink = baseUrl + billDocumentHtmlLink
                billDocTextEle = billDocRow.find("div", class_="text")
                span_element = billDocTextEle.find("span")
                if span_element:
                    strong_element = span_element.find("strong")
                if strong_element:
                    strong_text = strong_element.get_text()
                tuple = (strong_text, billDocumentFullLink)
                if billName in billNameStatusAndHtmlLinkDict:
                    billNameStatusAndHtmlLinkDict[billName].append(tuple)
                else:
                    billNameStatusAndHtmlLinkDict[billName] = [tuple]

    print(billNameStatusAndHtmlLinkDict)


def getBillDocuments(billHTMLList):
    print("placeholder")


if __name__ == "__main__":
    base_url = "https://legislature.mi.gov"
    url = "https://legislature.mi.gov/Bills/DailyReport?dateFrom=2024-03-29&dateTo=2024-04-09"
    bill_test = "https://legislature.mi.gov/Home/GetObject?objectName=2024-SR-0105"
    html_object = getWebpageContents(url)
    billDict = createBillUrlDict(html_object, base_url)
    getListOfBillHTMLFiles(base_url, billDict)
