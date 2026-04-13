import requests
import json

class XHSApiScraper:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = 'https://example.com/api'  # Replace with actual API endpoint
        self.login_url = f'{self.base_url}/login'
        self.detail_url = f'{self.base_url}/detail'
        self.report_path = 'report.html'

    def login(self, username, password):
        try:
            response = self.session.post(self.login_url, data={'username': username, 'password': password})
            response.raise_for_status()
            return response.json()  # Return relevant login info
        except requests.HTTPError as err:
            print(f'Login failed: {err}')
            return None
    
    def fetch_detail_page(self, item_id):
        try:
            response = self.session.get(f'{self.detail_url}/{item_id}')
            response.raise_for_status()
            return response.json()  # Return JSON data for the item
        except requests.HTTPError as err:
            print(f'Error fetching detail for item {item_id}: {err}')
            return None
    
    def generate_report(self, data):
        with open(self.report_path, 'w') as file:
            file.write('<html><body><h1>Report</h1><p>Data: {}</p></body></html>'.format(data))
    
    def scrape(self, username, password, item_ids):
        self.login(username, password)
        for item_id in item_ids:
            detail_data = self.fetch_detail_page(item_id)
            if detail_data:
                self.generate_report(detail_data)

# Example usage
if __name__ == '__main__':
    scraper = XHSApiScraper()
    # Replace with your actual username and password
    scraper.scrape('your_username', 'your_password', ['item1', 'item2'])
