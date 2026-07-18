#!/usr/bin/env python3
"""
Multi-site Sailing Boat Scraper
Monitors dba.dk, blocket.se, finn.no, kleinanzeigen.de, marktplaats.nl,
scanboat.com, and apolloduck.co.uk
Generates RSS feed for new sailing boats listed daily
Optimized for GitHub Actions
"""

import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime, timedelta, timezone
from feedgen.feed import FeedGenerator
import hashlib
import os
import re
import sys
from urllib.parse import urljoin
from typing import List, Dict, Optional


class SailingBoatScraper:
    def __init__(self, data_file='boat_data.json', rss_file='sailing_boats.xml'):
        self.data_file = data_file
        self.rss_file = rss_file
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.boats = self.load_data()
        self.stats = {
            'new_boats': 0,
            'total_boats': len(self.boats),
            'sites_scraped': 0,
            'sites_failed': 0,
            'total_sites': 0,
            'errors': []
        }

    def load_data(self):
        """Load previously scraped boat data"""
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_data(self):
        """Save scraped boat data"""
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.boats, f, ensure_ascii=False, indent=2)

    def generate_id(self, url):
        """Generate unique ID for a listing"""
        return hashlib.md5(url.encode()).hexdigest()

    def log_site_result(self, site_name: str, new_boats: List[Dict], error: Optional[Exception] = None):
        """Log the result of scraping a site"""
        if error:
            self.stats['sites_failed'] += 1
            self.stats['errors'].append(f"{site_name}: {str(error)}")
            print(f"❌ {site_name}: Failed - {error}")
        else:
            self.stats['sites_scraped'] += 1
            self.stats['new_boats'] += len(new_boats)
            print(f"✅ {site_name}: Found {len(new_boats)} new boats")

    def _now_iso_utc(self) -> str:
        """Return timezone-aware ISO timestamp in UTC."""
        return datetime.now(timezone.utc).isoformat()

    def _parse_dt(self, s: str) -> datetime:
        """
        Parse ISO string into timezone-aware datetime.
        - accepts trailing 'Z'
        - if tz is missing, assumes UTC (to handle old stored data)
        """
        s = (s or "").strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _scrape_schibsted_cards(self, site_name, url, fallback_location):
        """
        Shared scraper for Schibsted marketplaces (dba.dk, blocket.se, finn.no).
        All three render listings as 'article.sf-search-ad' cards with
        identical inner markup.
        """
        print(f"Scraping {site_name}...")
        new_boats = []

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            listings = soup.find_all('article', class_='sf-search-ad')

            for listing in listings[:20]:
                try:
                    link_elem = listing.find('a', class_='sf-search-ad-link')
                    if not link_elem or not link_elem.get('href'):
                        continue

                    boat_url = urljoin(url, link_elem['href'])
                    boat_id = self.generate_id(boat_url)

                    if boat_id in self.boats:
                        continue

                    title_elem = listing.find('h2')
                    title = title_elem.get_text(strip=True) if title_elem else 'Unknown boat'

                    amount_elem = listing.select_one('.t3.font-bold')
                    currency_elem = listing.select_one('.t4.font-bold')
                    if amount_elem:
                        price = amount_elem.get_text(strip=True)
                        if currency_elem:
                            price = f"{price} {currency_elem.get_text(strip=True)}"
                    else:
                        price = 'Price not listed'

                    location_elem = listing.select_one('.s-text-subtle span')
                    location = location_elem.get_text(strip=True) if location_elem else fallback_location

                    boat_data = {
                        'id': boat_id,
                        'title': title,
                        'price': price,
                        'location': location,
                        'url': boat_url,
                        'source': site_name,
                        'date_found': self._now_iso_utc(),   # ✅ timezone-aware
                    }

                    self.boats[boat_id] = boat_data
                    new_boats.append(boat_data)

                except Exception:
                    continue

            self.log_site_result(site_name, new_boats)

        except Exception as e:
            self.log_site_result(site_name, new_boats, e)

        return new_boats

    def scrape_dba_dk(self):
        """Scrape sailing boats from dba.dk"""
        return self._scrape_schibsted_cards(
            "dba.dk",
            "https://www.dba.dk/mobility/search/boat?class=2188",
            "Denmark",
        )

    def scrape_blocket_se(self):
        """Scrape sailing boats from blocket.se"""
        return self._scrape_schibsted_cards(
            "blocket.se",
            "https://www.blocket.se/mobility/search/boat?class=2188",
            "Sweden",
        )

    def scrape_finn_no(self):
        """Scrape sailing boats from finn.no"""
        return self._scrape_schibsted_cards(
            "finn.no",
            "https://www.finn.no/mobility/search/boat?class=2188&sales_form=120&sales_form=121",
            "Norway",
        )

    def scrape_kleinanzeigen_de(self):
        """Scrape sailing boats from kleinanzeigen.de"""
        site_name = "kleinanzeigen.de"
        print(f"Scraping {site_name}...")
        new_boats = []

        try:
            url = "https://www.kleinanzeigen.de/s-boote-bootszubehoer/segelboote/c211+boote_bootszubehoer.art_s:segelboote"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            listings = soup.find_all('article', class_='aditem')

            for listing in listings[:20]:
                try:
                    link_elem = listing.find('a', class_='ellipsis')
                    if not link_elem:
                        continue

                    boat_url = urljoin(url, link_elem['href'])
                    boat_id = self.generate_id(boat_url)

                    if boat_id in self.boats:
                        continue

                    title = link_elem.get_text(strip=True)

                    price_elem = listing.find('p', class_='aditem-main--middle--price-shipping--price')
                    price = price_elem.get_text(strip=True) if price_elem else 'VB'

                    location_elem = listing.find('div', class_='aditem-main--top--left')
                    location = location_elem.get_text(strip=True) if location_elem else 'Germany'

                    boat_data = {
                        'id': boat_id,
                        'title': title,
                        'price': price,
                        'location': location,
                        'url': boat_url,
                        'source': site_name,
                        'date_found': self._now_iso_utc(),   # ✅ timezone-aware
                    }

                    self.boats[boat_id] = boat_data
                    new_boats.append(boat_data)

                except Exception:
                    continue

            self.log_site_result(site_name, new_boats)

        except Exception as e:
            self.log_site_result(site_name, new_boats, e)

        return new_boats

    def scrape_marktplaats_nl(self):
        """Scrape sailing boats from marktplaats.nl"""
        site_name = "marktplaats.nl"
        print(f"Scraping {site_name}...")
        new_boats = []

        try:
            url = "https://www.marktplaats.nl/l/watersport-en-boten/kajuitzeilboten-en-zeiljachten/"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Marktplaats renders client-side; listings live in the
            # __NEXT_DATA__ JSON blob instead of the HTML.
            script = soup.find('script', id='__NEXT_DATA__')
            if not script or not script.string:
                raise ValueError("__NEXT_DATA__ script not found")
            next_data = json.loads(script.string)
            listings = next_data['props']['pageProps']['searchRequestAndResponse']['listings']

            for listing in listings[:20]:
                try:
                    vip_url = listing.get('vipUrl')
                    if not vip_url:
                        continue

                    boat_url = urljoin(url, vip_url)
                    boat_id = self.generate_id(boat_url)

                    if boat_id in self.boats:
                        continue

                    title = listing.get('title') or 'Unknown boat'

                    price_info = listing.get('priceInfo') or {}
                    price_cents = price_info.get('priceCents')
                    if price_cents:
                        price = f"€{price_cents / 100:,.0f}"
                        if price_info.get('priceType') == 'MIN_BID':
                            price += ' (bidding)'
                    else:
                        price_type = price_info.get('priceType', '')
                        price = price_type.replace('_', ' ').capitalize() if price_type else 'Price not listed'

                    location = (listing.get('location') or {}).get('cityName') or 'Netherlands'

                    boat_data = {
                        'id': boat_id,
                        'title': title,
                        'price': price,
                        'location': location,
                        'url': boat_url,
                        'source': site_name,
                        'date_found': self._now_iso_utc(),   # ✅ timezone-aware
                    }

                    self.boats[boat_id] = boat_data
                    new_boats.append(boat_data)

                except Exception:
                    continue

            self.log_site_result(site_name, new_boats)

        except Exception as e:
            self.log_site_result(site_name, new_boats, e)

        return new_boats

    def scrape_scanboat_com(self):
        """Scrape sailing boats from scanboat.com"""
        site_name = "scanboat.com"
        print(f"Scraping {site_name}...")
        new_boats = []

        try:
            url = ("https://www.scanboat.com/en/boat-market/boats"
                   "?SearchCriteria.BoatClassification=sail&SearchCriteria.Searched=true")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Search results live in boat-list__body; the page also has a
            # promo slider with unfiltered boats we must not pick up.
            result_body = soup.find('section', class_='boat-list__body')
            if not result_body:
                raise ValueError("boat-list__body not found")
            listings = result_body.find_all(['div', 'section'], class_=['item', 'promotion'])

            for listing in listings[:20]:
                try:
                    link_elem = listing.find('a', href=True)
                    if not link_elem:
                        continue

                    boat_url = urljoin(url, link_elem['href'])
                    boat_id = self.generate_id(boat_url)

                    if boat_id in self.boats:
                        continue

                    title_elem = listing.find('h2')
                    title = title_elem.get_text(strip=True) if title_elem else 'Unknown boat'

                    price_elem = listing.select_one('.item__header .right p')
                    price = price_elem.get_text(strip=True) if price_elem else 'Price not listed'

                    country_match = re.search(r'Country\s*:\s*([^|]+)', listing.get_text())
                    location = country_match.group(1).strip() if country_match else 'Scandinavia'

                    boat_data = {
                        'id': boat_id,
                        'title': title,
                        'price': price,
                        'location': location,
                        'url': boat_url,
                        'source': site_name,
                        'date_found': self._now_iso_utc(),   # ✅ timezone-aware
                    }

                    self.boats[boat_id] = boat_data
                    new_boats.append(boat_data)

                except Exception:
                    continue

            self.log_site_result(site_name, new_boats)

        except Exception as e:
            self.log_site_result(site_name, new_boats, e)

        return new_boats

    def scrape_apolloduck_uk(self):
        """Scrape sailing boats from apolloduck.co.uk"""
        site_name = "apolloduck.co.uk"
        print(f"Scraping {site_name}...")
        new_boats = []

        try:
            # _FeatureAdPanel blocks are site-wide paid promos (incl. motor
            # boats), so only take standard/free ads; limit=100 because the
            # server interleaves ~9 promos per 10 real ads.
            url = "https://www.apolloduck.co.uk/boats-for-sale/sail?sort=0&fx=GBP&limit=100&iso=gb"
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            listings = soup.select(
                'div.galleryPanels div._StandardAdPanel, div.galleryPanels div._FreeAdPanel'
            )

            for listing in listings[:20]:
                try:
                    title_elem = listing.select_one('._PanelTitle a')
                    if not title_elem or not title_elem.get('href'):
                        continue

                    boat_url = urljoin(url, title_elem['href'])
                    boat_id = self.generate_id(boat_url)

                    if boat_id in self.boats:
                        continue

                    title = title_elem.get_text(strip=True)

                    price = 'Price not listed'
                    location = 'UK'
                    for row in listing.select('table._PanelSpecTable tr'):
                        label_elem = row.find('td', class_='_PanelSpecLabel')
                        data_elem = row.find('td', class_='_PanelSpecData')
                        if not label_elem or not data_elem:
                            continue
                        label = label_elem.get_text(strip=True).rstrip(':')
                        if label == 'Price':
                            price = data_elem.get_text(strip=True)
                        elif label == 'Location':
                            location = data_elem.get_text(strip=True)

                    # Titles look like "For Sale: Finn 575 - £4,700"; strip
                    # both decorations since the RSS title appends the price.
                    title = re.sub(r'^For Sale:\s*', '', title)
                    title = re.sub(r'\s+-\s+£[\d,]+$', '', title)

                    boat_data = {
                        'id': boat_id,
                        'title': title,
                        'price': price,
                        'location': location,
                        'url': boat_url,
                        'source': site_name,
                        'date_found': self._now_iso_utc(),   # ✅ timezone-aware
                    }

                    self.boats[boat_id] = boat_data
                    new_boats.append(boat_data)

                except Exception:
                    continue

            self.log_site_result(site_name, new_boats)

        except Exception as e:
            self.log_site_result(site_name, new_boats, e)

        return new_boats

    def scrape_all(self):
        """Scrape all websites"""
        all_new_boats = []

        scrapers = [
            self.scrape_dba_dk,
            self.scrape_blocket_se,
            self.scrape_finn_no,
            self.scrape_kleinanzeigen_de,
            self.scrape_marktplaats_nl,
            self.scrape_scanboat_com,
            self.scrape_apolloduck_uk,
        ]
        self.stats['total_sites'] = len(scrapers)

        for i, scraper in enumerate(scrapers):
            all_new_boats.extend(scraper())
            if i < len(scrapers) - 1:
                time.sleep(1)

        self.save_data()
        self.stats['total_boats'] = len(self.boats)
        return all_new_boats

    def generate_rss(self):
        """Generate RSS feed from boat data"""
        fg = FeedGenerator()
        fg.title('Sailing Boats for Sale - Multi-site Feed')
        fg.link(href='https://example.com', rel='alternate')
        fg.description('New sailing boats from dba.dk, blocket.se, finn.no, kleinanzeigen.de, '
                       'marktplaats.nl, scanboat.com, and apolloduck.co.uk')
        fg.language('en')

        # Get boats from last 7 days (timezone-aware UTC cutoff)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)

        recent_boats = [
            boat for boat in self.boats.values()
            if self._parse_dt(boat['date_found']) > cutoff_date
        ]

        # Sort by date found (newest first)
        recent_boats.sort(key=lambda x: self._parse_dt(x['date_found']), reverse=True)

        for boat in recent_boats:
            fe = fg.add_entry()
            fe.id(boat['id'])
            fe.title(f"{boat['title']} - {boat['price']}")
            fe.link(href=boat['url'])
            fe.description(
                f"<strong>Price:</strong> {boat['price']}<br>"
                f"<strong>Location:</strong> {boat['location']}<br>"
                f"<strong>Source:</strong> {boat['source']}<br>"
                f"<strong>Found:</strong> {boat['date_found']}<br>"
                f"<a href='{boat['url']}'>View Listing</a>"
            )

            # ✅ feedgen requires timezone-aware datetime
            fe.published(self._parse_dt(boat['date_found']))

        fg.rss_file(self.rss_file)
        print(f"\n✅ RSS feed generated: {self.rss_file}")
        print(f"   Boats in feed (last 7 days): {len(recent_boats)}")
        return self.rss_file

    def print_stats(self):
        """Print scraping statistics"""
        print("\n" + "=" * 60)
        print("SCRAPING STATISTICS")
        print("=" * 60)
        print(f"Sites scraped successfully: {self.stats['sites_scraped']}/{self.stats['total_sites']}")
        print(f"Sites failed: {self.stats['sites_failed']}/{self.stats['total_sites']}")
        print(f"New boats found: {self.stats['new_boats']}")
        print(f"Total boats in database: {self.stats['total_boats']}")

        if self.stats['errors']:
            print(f"\nErrors encountered:")
            for error in self.stats['errors']:
                print(f"  - {error}")

        print("=" * 60)


def main():
    print("=" * 60)
    print("SAILING BOAT SCRAPER - GitHub Actions Optimized")
    print("=" * 60)
    print(f"Run started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    scraper = SailingBoatScraper()

    print(f"Previous database size: {len(scraper.boats)} boats\n")
    print("Starting scraping process...\n")

    new_boats = scraper.scrape_all()

    scraper.print_stats()

    if new_boats:
        print(f"\n📋 New boats found ({len(new_boats)}):")
        for i, boat in enumerate(new_boats[:15], 1):
            print(f"  {i}. {boat['title']} ({boat['source']}) - {boat['price']}")
        if len(new_boats) > 15:
            print(f"  ... and {len(new_boats) - 15} more")
    else:
        print("\n📋 No new boats found in this run")

    print("\n" + "=" * 60)
    print("Generating RSS feed...")
    print("=" * 60)

    scraper.generate_rss()

    print("\n✨ Scraper completed successfully!")
    print(f"Run finished: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Exit with non-zero code if all sites failed
    if scraper.stats['sites_scraped'] == 0:
        print("\n⚠️  WARNING: All sites failed to scrape!")
        sys.exit(1)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Scraper interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
