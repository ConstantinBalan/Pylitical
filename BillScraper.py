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
def getListOfBillHTMLFiles(billDict):

    for introducedBillUrl in billDict["Introduced"]:
        introBillHTML = getWebpageContents(introducedBillUrl)
    for chamberPassedBillUrl in billDict["Passed By Chamber"]:
        chambPassBillHTML = getWebpageContents(chamberPassedBillUrl)
    for enrolledBillUrl in billDict["Enrolled"]:
        enrollBillHTML = getWebpageContents(enrolledBillUrl)
    for adoptedBillUrl in billDict["Adopted"]:
        adoptBillHTML = getWebpageContents(adoptedBillUrl)


if __name__ == "__main__":
    base_url = "https://legislature.mi.gov"
    url = "https://legislature.mi.gov/Bills/DailyReport?dateFrom=2024-03-29&dateTo=2024-04-09"
    bill_test = "https://legislature.mi.gov/Home/GetObject?objectName=2024-SR-0105"
    html_object = getWebpageContents(url)
    billDict = createBillUrlDict(html_object, base_url)
    getListOfBillHTMLFiles(billDict)
