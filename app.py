import streamlit as st
import requests
import json
from datetime import datetime
import os
import pandas as pd
import csv
import io

# Page configuration
st.set_page_config(
    page_title="Deliverect Menu & Inventory Checker",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📋 Midnyt Menu & Inventory Checker")
st.markdown("Check menu items and inventory across your catalogs")

# Hardcoded account ID
account = "690b7701ad081789f16340e5"

def getToken():
    client_id = None
    client_secret = None
    
    # Try to get credentials from Streamlit secrets first
    try:
        client_id = st.secrets["CLIENT_ID"]
        client_secret = st.secrets["CLIENT_SECRET"]
    except (KeyError, FileNotFoundError):
        # Fall back to .env file
        try:
            from dotenv import load_dotenv
            load_dotenv()
            client_id = os.getenv("CLIENT_ID")
            client_secret = os.getenv("CLIENT_SECRET")
        except:
            pass
    
    if not client_id or not client_secret:
        st.error("❌ CLIENT_ID and CLIENT_SECRET not found. Please configure .env file or Streamlit secrets.")
        st.info("""
        **For Streamlit Cloud/Secrets:**
        Create `.streamlit/secrets.toml` with:
        ```
        CLIENT_ID = "your_client_id"
        CLIENT_SECRET = "your_client_secret"
        ```
        
        **For local .env file:**
        Create `.env` with:
        ```
        CLIENT_ID=your_client_id
        CLIENT_SECRET=your_client_secret
        ```
        """)
        return None
    
    url = "https://api.deliverect.io/oauth/token"
    payload = json.dumps({
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": "https://api.deliverect.com",
        "grant_type": "token"
    })
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.request("POST", url, headers=headers, data=payload).json()
        return response.get("access_token")
    except Exception as e:
        st.error(f"Error getting token: {str(e)}")
        return None

# Get headers
def get_headers():
    token = getToken()
    if token:
        return {'Authorization': f'Bearer {token}'}
    return None
# API Functions
def getAllChannelMenus(accountId, headers):
    menuIds = []
    url = f"https://api.deliverect.io/channelMenus?where={{\"account\":\"{accountId}\"}}"
    response = requests.request("GET", url, headers=headers).json()
    for menu in response.get("_items", []): 
        menuIds.append(menu.get("_id"))
    return menuIds

def getCategoryDetails(categoryId, headers):
    """Get category details including name, subProducts and subCategories"""
    url = f"https://api.deliverect.io/channelCategories/{categoryId}"
    response = requests.request("GET", url, headers=headers).json()
    return {
        'name': response.get("name", "Unknown"),
        'subProducts': response.get("subProducts", []),
        'subCategories': response.get("subCategories", [])
    }

def getAllProducts(accountId, headers, progress_callback=None):
    all_products = []
    max_results = 500
    page = 1
    
    while True:
        url = f"https://api.deliverect.io/catalog/accounts/{accountId}/items"
        params = {
            "visible": True,
            "max_results": max_results,
            "sort": "-_id",
            "page": page
        }
        
        try:
            raw_response = requests.request("POST", url, headers=headers, json=params)
            
            # Check HTTP status
            if raw_response.status_code != 200:
                error_msg = f"API Error: Status {raw_response.status_code}"
                try:
                    error_detail = raw_response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {raw_response.text[:200]}"
                raise Exception(error_msg)
            
            response = raw_response.json()
            
            # Check for error in response
            if "error" in response or "_error" in response:
                error_detail = response.get("error") or response.get("_error")
                raise Exception(f"API returned error: {error_detail}")
            
            items = response.get("_items", [])
            
            for item in items:
                item_info = {"id": item.get("_id"), "plu": item.get("plu"), "name": item.get("name", "Unknown")}
                all_products.append(item_info)
            
            if progress_callback:
                progress_callback(f"Fetched page {page}: {len(items)} items (Total: {len(all_products)})")
            
            next_page = response.get("_links", {}).get("next", {})
            if next_page:
                page += 1
            else:
                break
                
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error on page {page}: {str(e)}")
            raise
    
    return all_products

def getProductInfo(productId, products_dict):
    """Get product info (PLU and name) by product ID from products dictionary"""
    product = products_dict.get(productId)
    if product:
        return {
            "plu": product.get("plu"),
            "name": product.get("name", "Unknown")
        }
    return None

def processSubCategory(subCategoryId, products_dict, location_name, all_items, headers, indent="    "):
    """Process a subcategory and its nested subcategories recursively"""
    if not subCategoryId:
        return
        
    subCategory_details = getCategoryDetails(subCategoryId, headers)
    subCategory_name = subCategory_details.get('name', 'Unknown')
    nested_subCategories = subCategory_details.get('subCategories', [])
    subProducts = subCategory_details.get('subProducts', [])
    
    # If this subcategory has more subcategories, loop over those first
    if nested_subCategories:
        for nestedSubCategoryId in nested_subCategories:
            processSubCategory(nestedSubCategoryId, products_dict, location_name, all_items, headers, indent + "  ")
    
    # Then loop over subProducts in this subcategory
    if subProducts:
        for product_id in subProducts:
            product_info = getProductInfo(product_id, products_dict)
            if product_info and product_info.get("plu"):
                all_items.append({
                    'Location': location_name,
                    'PLU': product_info.get("plu"),
                    'Product Name': product_info.get("name", "Unknown"),
                    'Category Name': subCategory_name
                })

def getItemsInChannelMenu(menuId, accountId, location_name, products_dict, headers):
    """Extract all PLUs from all categories in a channel menu"""
    all_items = []
    url = f"https://api.deliverect.io/channelMenus/{menuId}"
    response = requests.request("GET", url, headers=headers).json()
    channelCategories = response.get("channelCategories", [])
    
    # Loop over categories
    for categoryId in channelCategories:
        if not categoryId:
            continue
            
        category_details = getCategoryDetails(categoryId, headers)
        category_name = category_details.get('name', 'Unknown')
        subCategories = category_details.get('subCategories', [])
        subProducts = category_details.get('subProducts', [])
        
        # If category has subcategories, loop over them
        if subCategories:
            for subCategoryId in subCategories:
                processSubCategory(subCategoryId, products_dict, location_name, all_items, headers)
        
        # Also check for direct subProducts in the category
        if subProducts:
            for product_id in subProducts:
                product_info = getProductInfo(product_id, products_dict)
                if product_info and product_info.get("plu"):
                    all_items.append({
                        'Location': location_name,
                        'PLU': product_info.get("plu"),
                        'Product Name': product_info.get("name", "Unknown"),
                        'Category Name': category_name
                    })
    
    return all_items

def getLocationNameAndId(accountId, menuName, headers):
    """Get both location name and ID based on menu name"""
    url = f"https://api.deliverect.io/locations?where={{\"account\":\"{accountId}\"}}"
    response = requests.request("GET", url, headers=headers).json()
    for location in response.get("_items", []):
        location_name = location.get("name", "")
        if location_name and menuName.lower() in location_name.lower():
            return {
                "name": location_name,
                "id": location.get("_id")
            }
    return {"name": "Name Not Found", "id": None}



def getInventory(account: str, headers, progress_callback=None):
    page = 1
    inventory_url = f"https://api.deliverect.io/catalog/accounts/{account}/inventory"
    inventory_items = []
    
    while True:
        payload_inventory = {"sort":"-_id","max_results":50,"locations":[], "page": page}
        
        try:
            response = requests.post(inventory_url, headers=headers, json=payload_inventory)
            
            # Check HTTP status
            if response.status_code != 200:
                error_msg = f"API Error: Status {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {response.text[:200]}"
                raise Exception(error_msg)
            
            inventory = response.json()
            
            # Check for error in response
            if "error" in inventory or "_error" in inventory:
                error_detail = inventory.get("error") or inventory.get("_error")
                raise Exception(f"API returned error: {error_detail}")
            
            items = inventory.get("_items", [])
            if not items:
                break
            
            inventory_items.extend(items)
            
            if progress_callback:
                progress_callback(f"Fetching inventory on page {page}")
            
            page += 1
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error on page {page}: {str(e)}")
            raise
    
    return inventory_items

def buildInventoryLookup(inventory: list):
    """Build a set of (plu, location) tuples for O(1) lookup"""
    lookup = set()
    for item in inventory:
        plu = item.get("plu")
        if plu:
            locations = item.get("locations", [])
            for loc_obj in locations:
                location_id = loc_obj.get("location")
                if location_id:
                    lookup.add((plu, location_id))
    return lookup

def getLocationName(location: str, headers):
    url = f"https://api.deliverect.io/locations/{location}"
    response = requests.get(url, headers=headers)
    return response.json().get("name")

def getAccountName(account: str, headers):
    url = f"https://api.deliverect.io/accounts/{account}"
    response = requests.get(url, headers=headers)
    return response.json().get("name")


def checkMenuItemsInventory(menu_items: list, location_id: str, inventory_lookup: set):
    """Check which menu items are missing inventory for a specific location"""
    missing_items = []
    for item in menu_items:
        plu = item.get('PLU')
        if plu and (plu, location_id) not in inventory_lookup:
            missing_items.append(item)
    return missing_items


# Main Processing
st.divider()

if st.button("🧮 Calculate", type="primary", use_container_width=False):
    headers = get_headers()
    if not headers:
        st.error("❌ Failed to get authentication token. Please check your .env file or Streamlit secrets.")
    else:
            try:
                # Initialize progress tracking
                progress_container = st.container()
                
                with progress_container:
                    # Fetch all products
                    st.info("📦 Fetching all products...")
                    status_text = st.empty()
                    
                    def progress_callback(msg):
                        status_text.text(msg)
                    
                    try:
                        all_products = getAllProducts(account, headers, progress_callback)
                        products_dict = {product.get("id"): product for product in all_products}
                        status_text.empty()
                        
                        if len(products_dict) == 0:
                            st.warning("⚠️ No products found. This might be an API access issue or the account has no products.")
                        else:
                            st.success(f"✅ Loaded {len(products_dict)} products")
                    except Exception as e:
                        status_text.empty()
                        st.error(f"❌ Failed to fetch products: {str(e)}")
                        raise
                
                with progress_container:
                    # Fetch inventory
                    st.info("📊 Fetching inventory...")
                    status_text = st.empty()
                    
                    try:
                        inventory = getInventory(account, headers, progress_callback)
                        inventory_lookup = buildInventoryLookup(inventory)
                        status_text.empty()
                        st.success(f"✅ Loaded inventory for {len(inventory)} items")
                    except Exception as e:
                        status_text.empty()
                        st.error(f"❌ Failed to fetch inventory: {str(e)}")
                        raise
                
                with progress_container:
                    # Get all menus
                    st.info("🔍 Fetching menus...")
                    menu_ids = getAllChannelMenus(account, headers)
                    st.success(f"✅ Found {len(menu_ids)} menus to process")
                
                st.divider()
                st.header("📋 Menu Processing Results")
                
                # Track menus without location IDs
                menus_without_location = []
                
                # Create tabs for each menu
                if menu_ids:
                    for idx, menu_id in enumerate(menu_ids):
                        url = f"https://api.deliverect.io/channelMenus/{menu_id}"
                        menu_response = requests.request("GET", url, headers=headers).json()
                        menu_name = menu_response.get("name", "Unknown Menu")
                        
                        with st.expander(f"📋 {menu_name}", expanded=True):
                            col1, col2 = st.columns([2, 1])
                            
                            # Get location info
                            location_info = getLocationNameAndId(account, menu_name, headers)
                            location_name = location_info["name"]
                            location_id = location_info["id"]
                            
                            with col1:
                                st.metric("📍 Location", location_name)
                            with col2:
                                if location_id:
                                    st.metric("🆔 Location ID", location_id[:8] + "...")
                                else:
                                    st.metric("🆔 Location ID", "Not Found")
                            
                            # Get menu items
                            with st.spinner(f"Processing {menu_name}..."):
                                items = getItemsInChannelMenu(menu_id, account, location_name, products_dict, headers)
                            
                            if items:
                                df = pd.DataFrame(items)
                                
                                # Display metrics
                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric("📦 Total Items", len(items))
                                with col2:
                                    unique_categories = df['Category Name'].nunique()
                                    st.metric("📂 Categories", unique_categories)
                                with col3:
                                    unique_plus = df['PLU'].nunique()
                                    st.metric("🔢 Unique PLUs", unique_plus)
                                
                                # Display data
                                st.subheader("Menu Items")
                                st.dataframe(df, use_container_width=True, height=300)
                                
                                # Download button for menu items
                                csv_buffer = io.StringIO()
                                df.to_csv(csv_buffer, index=False)
                                st.download_button(
                                    label=f"📥 Download Menu Items CSV",
                                    data=csv_buffer.getvalue(),
                                    file_name=f"{menu_name.replace(' ', '_')}.csv",
                                    mime="text/csv",
                                    key=f"download_menu_{menu_id}"
                                )
                                
                                # Check inventory
                                if location_id:
                                    st.divider()
                                    st.subheader("🔍 Inventory Check")
                                    
                                    missing_items = checkMenuItemsInventory(items, location_id, inventory_lookup)
                                    
                                    if missing_items:
                                        st.warning(f"⚠️ Found {len(missing_items)} items WITHOUT inventory")
                                        df_missing = pd.DataFrame(missing_items)
                                        st.dataframe(df_missing, use_container_width=True, height=200)
                                        
                                        # Download button for missing inventory
                                        missing_csv_buffer = io.StringIO()
                                        df_missing.to_csv(missing_csv_buffer, index=False)
                                        st.download_button(
                                            label=f"📥 Download Missing Inventory Report",
                                            data=missing_csv_buffer.getvalue(),
                                            file_name=f"MissingInventory_{menu_name.replace(' ', '_')}.csv",
                                            mime="text/csv",
                                            key=f"download_missing_{menu_id}"
                                        )
                                    else:
                                        st.success(f"✅ All {len(items)} menu items have inventory set up!")
                                else:
                                    st.warning("⚠️ Could not find location ID - skipping inventory check")
                                    menus_without_location.append({
                                        "menu_name": menu_name,
                                        "menu_id": menu_id,
                                        "location_name": location_name,
                                        "item_count": len(items)
                                    })
                            else:
                                st.warning("⚠️ No items found in this menu")
                    
                    # Summary
                    st.divider()
                    st.header("📊 Processing Summary")
                    
                    if menus_without_location:
                        st.warning(f"🚨 {len(menus_without_location)} menu(s) could not be matched to locations")
                        df_unmatched = pd.DataFrame(menus_without_location)
                        st.dataframe(df_unmatched, use_container_width=True)
                        
                        with st.expander("💡 Action Required"):
                            st.markdown("""
                            - Verify the menu names match actual location names
                            - Check if these locations exist in the account
                            - Update the menu name matching logic if needed
                            """)
                    else:
                        st.success("✅ All menus successfully matched to locations!")
                else:
                    st.warning("No menus found for this account")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                with st.expander("View Error Details"):
                    st.exception(e)

# Instructions
with st.expander("ℹ️ How to Use"):
    st.markdown("""
    ### Setup
    Create a `.env` file in the project root with:
    ```
    CLIENT_ID=your_client_id_here
    CLIENT_SECRET=your_client_secret_here
    ```
    
    Or configure Streamlit secrets with the same keys.
    
    ### Usage
    1. **Click "Calculate"** to start processing
    2. **View Results** in expandable sections for each menu
    3. **Download CSV files** for menu items and missing inventory reports
    
    ### Features
    - 📋 View all menu items per location
    - 🔍 Check which items are missing inventory
    - 📥 Download reports as CSV files
    - 📊 Summary of all processed menus
    """)

# Footer
st.divider()
st.caption("Powered by Midnyt - Deliverect Menu & Inventory Checker v1.0")
