"""Category templates for product information (Batch 12, Phase 4). DATA ONLY - no imports, no logic.

Each of the four locked pillars has:
- `subcategories`: the choices offered in the product form (a product may still carry an older free-text sub-category).
- `groups`: labelled attribute groups shown as sections of the product form. Each field:
    key       stored under product.attributes[key] (keys of the original ATTRIBUTE_SPECS are kept unchanged)
    label     shown to people
    type      text | textarea | number | date | select | multi | bool
    max       text: max length · number: max value
    options   select / multi choices
    unit      shown next to numbers
    required  True (every product in the pillar), or a list of sub-categories it is required for. Enforced only when a product
              is SUBMITTED for review through the product studio (drafts may be incomplete; older APIs are unchanged).
    variant   True if the field can also be a variant dimension
    help      one line of guidance
- `review_flags`: things the reviewing admin must check by hand (legal / regulatory requirements are flagged for review, never
  silently enforced, because they depend on the product and must be confirmed by someone qualified).

New categories or fields are added here; the form, the validation and the admin review read this structure.
"""

COLOURS = ["Red", "Maroon", "Pink", "Orange", "Yellow", "Mustard", "Green", "Teal", "Blue", "Navy", "Purple", "Violet", "Black", "White",
           "Off-white", "Cream", "Beige", "Brown", "Grey", "Gold", "Silver", "Multicolour"]
OCCASIONS = ["Daily wear", "Office", "Festive", "Wedding", "Party", "Casual", "Traditional"]

TEMPLATES = {
    "Sarees": {
        "subcategories": ["Silk", "Cotton", "Banarasi", "Kanjeevaram", "Chiffon", "Georgette", "Linen", "Handloom", "Printed", "Embroidered", "Other"],
        "groups": [
            {"id": "fabric_weave", "label": "Fabric & weave", "fields": [
                {"key": "fabric", "label": "Fabric", "type": "text", "max": 60, "required": True, "variant": True, "help": "e.g. Pure silk, Cotton silk"},
                {"key": "weave_style", "label": "Weave / technique", "type": "text", "max": 60, "help": "e.g. Zari weave, Ikat, Block print"},
                {"key": "pattern", "label": "Pattern", "type": "select", "options": ["Solid", "Printed", "Woven", "Embroidered", "Checked", "Striped", "Floral", "Temple border", "Other"]},
                {"key": "colour", "label": "Main colour", "type": "select", "options": COLOURS, "required": True, "variant": True},
            ]},
            {"id": "size_blouse", "label": "Length & blouse", "fields": [
                {"key": "length_m", "label": "Saree length", "type": "number", "max": 20, "unit": "m", "required": True},
                {"key": "blouse_piece", "label": "Blouse piece included", "type": "bool"},
                {"key": "blouse_length_m", "label": "Blouse piece length", "type": "number", "max": 5, "unit": "m"},
                {"key": "included_accessories", "label": "Also included", "type": "text", "max": 120},
            ]},
            {"id": "use_care", "label": "Occasion & care", "fields": [
                {"key": "occasion", "label": "Occasion", "type": "multi", "options": OCCASIONS},
                {"key": "care_instructions", "label": "Care instructions", "type": "textarea", "max": 300, "required": True, "help": "e.g. Dry clean only"},
                {"key": "origin", "label": "Region / weaving origin", "type": "text", "max": 80, "help": "e.g. Varanasi"},
                {"key": "country_of_origin", "label": "Country of origin", "type": "text", "max": 60, "required": True},
            ]},
        ],
        "review_flags": ["Handloom / silk-mark claims need supporting proof (e.g. Silk Mark label or a certificate)."],
    },
    "Fashion Products": {
        "subcategories": ["Kurtas & sets", "Tops", "Dresses", "Ethnic wear", "Bottom wear", "Dupattas & stoles", "Footwear", "Bags", "Jewellery", "Accessories", "Other"],
        "groups": [
            {"id": "type_fit", "label": "Type & fit", "fields": [
                {"key": "product_type", "label": "Product type", "type": "text", "max": 60, "required": True, "help": "e.g. Straight kurta"},
                {"key": "gender", "label": "Made for", "type": "select", "options": ["Women", "Men", "Girls", "Boys", "Unisex"], "required": True},
                {"key": "fit", "label": "Fit", "type": "select", "options": ["Regular", "Slim", "Relaxed", "Oversized", "Not applicable"]},
                {"key": "style", "label": "Style", "type": "text", "max": 60},
            ]},
            {"id": "material_size", "label": "Material & size", "fields": [
                {"key": "material", "label": "Material / fabric", "type": "text", "max": 80, "required": True, "variant": True},
                {"key": "size", "label": "Size (single-size products)", "type": "text", "max": 30, "variant": True,
                 "help": "Products sold in several sizes use variants instead"},
                {"key": "size_chart", "label": "Size chart", "type": "textarea", "max": 1000, "help": "Measurements per size (chest, waist, length...)"},
                {"key": "colour", "label": "Colour", "type": "select", "options": COLOURS, "variant": True},
                {"key": "pattern", "label": "Pattern", "type": "text", "max": 60},
            ]},
            {"id": "use_care", "label": "Occasion & care", "fields": [
                {"key": "occasion", "label": "Occasion", "type": "multi", "options": OCCASIONS},
                {"key": "care_instructions", "label": "Care instructions", "type": "textarea", "max": 300, "required": True},
                {"key": "country_of_origin", "label": "Country of origin", "type": "text", "max": 60, "required": True},
            ]},
        ],
        "review_flags": ["Brand names on the listing must belong to the vendor or be backed by a brand authorisation."],
    },
    "Makeup, Beauty & Skincare": {
        "subcategories": ["Skincare", "Haircare", "Makeup", "Fragrance", "Bath & body", "Personal care", "Ayurvedic & herbal", "Tools & accessories", "Other"],
        "groups": [
            {"id": "product", "label": "Product", "fields": [
                {"key": "product_type", "label": "Product type", "type": "text", "max": 60, "required": True, "help": "e.g. Face serum, Lipstick"},
                {"key": "net_quantity", "label": "Net quantity", "type": "text", "max": 40, "required": True, "variant": True, "help": "e.g. 50 ml, 100 g"},
                {"key": "skin_type", "label": "Suitable skin types", "type": "multi", "options": ["All", "Dry", "Oily", "Combination", "Normal", "Sensitive"]},
                {"key": "hair_type", "label": "Suitable hair types", "type": "multi", "options": ["All", "Dry", "Oily", "Curly", "Straight", "Coloured", "Damaged"]},
                {"key": "shade", "label": "Shade (single-shade products)", "type": "text", "max": 40, "variant": True},
            ]},
            {"id": "ingredients_use", "label": "Ingredients & use", "fields": [
                {"key": "ingredients", "label": "Ingredients", "type": "textarea", "max": 1000, "required": True},
                {"key": "directions", "label": "How to use", "type": "textarea", "max": 500, "required": True},
                {"key": "warnings", "label": "Warnings / precautions", "type": "textarea", "max": 500},
            ]},
            {"id": "shelf_life", "label": "Batch & shelf life", "fields": [
                {"key": "batch_no", "label": "Batch number", "type": "text", "max": 40},
                {"key": "expiry_date", "label": "Expiry date (of current stock)", "type": "date", "max": 10},
                {"key": "shelf_life_months", "label": "Shelf life", "type": "number", "max": 120, "unit": "months"},
                {"key": "storage_instructions", "label": "Storage instructions", "type": "text", "max": 200},
            ]},
            {"id": "maker", "label": "Manufacturer & licence", "fields": [
                {"key": "manufacturer", "label": "Manufacturer name", "type": "text", "max": 120, "required": True},
                {"key": "manufacturer_address", "label": "Manufacturer address", "type": "textarea", "max": 300},
                {"key": "importer_details", "label": "Importer (imported products)", "type": "textarea", "max": 300},
                {"key": "licence_number", "label": "Manufacturing / import licence number", "type": "text", "max": 60,
                 "help": "As printed on the pack, if the product carries one"},
                {"key": "country_of_origin", "label": "Country of origin", "type": "text", "max": 60, "required": True},
            ]},
        ],
        "review_flags": ["Cosmetics: check the licence number and label details against the pack photos.",
                         "Ayurvedic / herbal products may need a separate licence; confirm before approval.",
                         "Claims such as 'cures', 'treats' or 'clinically proven' need evidence."],
    },
    "Household Essentials": {
        "subcategories": ["Kitchen & dining", "Cleaning", "Storage", "Home decor", "Bath", "Pooja items", "Appliances (small)", "Other"],
        "groups": [
            {"id": "product", "label": "Product", "fields": [
                {"key": "product_type", "label": "Product type", "type": "text", "max": 60, "required": True},
                {"key": "material", "label": "Material", "type": "text", "max": 80, "required": True, "variant": True},
                {"key": "quantity", "label": "Quantity / pack contents", "type": "text", "max": 60, "variant": True, "help": "e.g. Set of 6"},
                {"key": "colour", "label": "Colour", "type": "select", "options": COLOURS, "variant": True},
            ]},
            {"id": "size", "label": "Size & weight", "fields": [
                {"key": "dimensions", "label": "Product dimensions", "type": "text", "max": 60, "help": "L x W x H, e.g. 30 x 20 x 10 cm"},
                {"key": "weight_g", "label": "Product weight", "type": "number", "max": 100000, "unit": "g"},
                {"key": "capacity", "label": "Capacity", "type": "text", "max": 40, "help": "e.g. 1.5 L"},
            ]},
            {"id": "use_care", "label": "Use, care & warranty", "fields": [
                {"key": "usage_instructions", "label": "How to use", "type": "textarea", "max": 500},
                {"key": "care_instructions", "label": "Care instructions", "type": "textarea", "max": 300},
                {"key": "safety_info", "label": "Safety information", "type": "textarea", "max": 500, "required": ["Appliances (small)", "Cleaning"]},
                {"key": "warranty", "label": "Warranty", "type": "text", "max": 120, "required": ["Appliances (small)"], "help": "e.g. 1 year manufacturer warranty"},
                {"key": "country_of_origin", "label": "Country of origin", "type": "text", "max": 60, "required": True},
            ]},
        ],
        "review_flags": ["Electrical appliances may need a BIS certification mark; confirm before approval.",
                         "Cleaning chemicals: check the safety information against the label."],
    },
}

# The sections of the product studio, in order. `vendor` = the vendor edits it; `admin_only` sections are hidden from vendors.
SECTIONS = [
    {"id": "basics", "label": "Basic information"},
    {"id": "media", "label": "Images"},
    {"id": "pricing", "label": "Price & tax"},
    {"id": "variants", "label": "Variants & stock"},
    {"id": "details", "label": "Product details"},
    {"id": "shipping", "label": "Shipping & returns"},
    {"id": "compliance", "label": "Documents & declarations"},
    {"id": "review", "label": "Review & submit"},
]
