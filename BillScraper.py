from bs4 import BeautifulSoup
import requests
import ChatSummarize

def billsByDate(dateRange):
    print('Placeholder')

def billsByCategory(categoryName):
    print('Placeholder')

def main():
    print('Placeholder')

def tempFuncForGettingBills(parsableHTML):
    soup = BeautifulSoup(parsableHTML, 'html.parser')
    titleOfBillStates = {}
    titleNames = ['Introduced', 'Passed by Chamber', 'Enrolled', 'Adopted']
    for name in titleNames:
        titleElement = soup.find('h3', text = name)

        if titleElement:
            tableElement = titleElement.find_next_sibling()
            titleOfBillStates[name] = tableElement
        else:
            titleOfBillStates[name] = None
    print(titleOfBillStates)

def getWebpageContents(url):
    response = requests.get(url)

    if response.status_code == 200:
       html_content = response.text
       print(html_content)
    else:
        print(f"Failed to fetch HTML from {url}. Status code: {response.status_code}")
    return html_content

if __name__ == "__main__":
    url = "https://legislature.mi.gov/Bills/DailyReport?dateFrom=2024-03-29&dateTo=2024-04-09"
    html_object = getWebpageContents(url)
    tempFuncForGettingBills(html_object)
