"""
ABC Buttons - Product Catalog Master & Pricing Matrix
Featuring 100% Genuine Real Factory Photography Products.
All quantities and rates strictly in GROSS (1 Gross = 144 Pieces).
"""

SAMPLE_CATALOG = [
    {
        "sku": "ABC-136",
        "name": "ABC-136 White Pearl Agoya Shell Button (Bulk Stock)",
        "category": "Shell / MOP",
        "material": "Agoya Japanese Sea Shell",
        "finish": "Ultra-White High Gloss Polish",
        "holes": "2-Hole & 4-Hole Mixed Sizes",
        "size_ligne": "14L / 18L (8.9 - 11.5 mm)",
        "recommended_garment": "Tuxedo Shirts, Collars, High-Volume Formal Shirt Programs",
        "rate_per_gross": 175,
        "stock_gross": 1250,
        "description": "ABC Buttons official SKU ABC-136. High-volume staple shell button in bright white luster for shirt exporters."
    },
    {
        "sku": "ABC-137",
        "name": "ABC-137 Caramel Gold MOP Shell Button",
        "category": "Shell / MOP",
        "material": "Golden Lip Pearl Shell",
        "finish": "Warm Amber-Gold Pearl Luster",
        "holes": "4-Hole Raised Rim",
        "size_ligne": "24L (15.2 mm)",
        "recommended_garment": "Beige/Tan Suits, Cashmere Cardigans, Safari Jackets",
        "rate_per_gross": 340,
        "stock_gross": 280,
        "description": "ABC Buttons official SKU ABC-137. Rich champagne gold natural shell luster with smooth beveled rim."
    },
    {
        "sku": "ABC-138",
        "name": "ABC-138 Midnight Black Lip Shell Button",
        "category": "Shell / MOP",
        "material": "Tahitian Black Lip Oyster Shell",
        "finish": "Deep Dark Charcoal Luster with Green/Pink Iridescence",
        "holes": "4-Hole",
        "size_ligne": "24L (15.2 mm)",
        "recommended_garment": "Black Tuxedos, Navy Evening Blazers, Luxury Outerwear",
        "rate_per_gross": 390,
        "stock_gross": 195,
        "description": "ABC Buttons official SKU ABC-138. Premium dark Tahitian oyster shell with peacock overtone iridescence."
    },
    {
        "sku": "ABC-139",
        "name": "ABC-139 Natural White River Shell Button (2-Hole Rim)",
        "category": "Shell / MOP",
        "material": "River Shell / MOP",
        "finish": "Natural Iridescent Pearl Gloss with Raised Rim",
        "holes": "2-Hole with Rim",
        "size_ligne": "24L (15.2 mm)",
        "recommended_garment": "Kurta-Pajama, Linen Shirts, Designer Nehru Jackets, Summer Blouses",
        "rate_per_gross": 290,
        "stock_gross": 520,
        "description": "ABC Buttons official SKU ABC-139. Pure natural river shell with raised outer rim and 2 centered drilled holes. Premium organic luster."
    },
    {
        "sku": "ABC-140",
        "name": "ABC-140 Bronze Luster Shell Button",
        "category": "Shell / MOP",
        "material": "Natural Sea Shell",
        "finish": "Metallic Bronze Sheen",
        "holes": "4-Hole Rim",
        "size_ligne": "20L (12.7 mm)",
        "recommended_garment": "Brown Linen Blazers, Chinos, Bespoke Trousers",
        "rate_per_gross": 270,
        "stock_gross": 340,
        "description": "ABC Buttons official SKU ABC-140. Unique bronze earth-tone shell with natural organic streaks."
    },
    {
        "sku": "ABC-141",
        "name": "ABC-141 Smoky Gunmetal Trocas Shell Button (4-Hole)",
        "category": "Shell / MOP",
        "material": "Trocas / Black MOP Shell",
        "finish": "Smoky Grey Iridescent Pearl with Rim",
        "holes": "4-Hole Center Well",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Luxury Men's Formal Dress Shirts, Cuffs, Charcoal Suits",
        "rate_per_gross": 210,
        "stock_gross": 780,
        "description": "ABC Buttons official SKU ABC-141. Dark smoky grey hue with natural mother-of-pearl sheen. Beveled 4-hole center well."
    },
    {
        "sku": "ABC-142",
        "name": "ABC-142 Ocean Turquoise & Teal Dyed MOP Button",
        "category": "Shell / MOP",
        "material": "Natural Shell / Trocas",
        "finish": "Vibrant Turquoise Blue Luster with Natural Underside",
        "holes": "2-Hole Flat Face",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Resort Wear, Women's Luxury Shirts, Designer Silk Kurtis, Contrast Linen Shirts",
        "rate_per_gross": 320,
        "stock_gross": 410,
        "description": "ABC Buttons official SKU ABC-142. Custom dyed turquoise teal color with deep iridescence and natural mottled back."
    },
    {
        "sku": "ABC-143",
        "name": "ABC-143 Natural Spotted River Shell Button (2-Hole)",
        "category": "Shell / MOP",
        "material": "Natural River Shell / MOP",
        "finish": "Natural Iridescent White Pearl with Dark Smoky & Plum Spotted Marks",
        "holes": "2-Hole with Raised Rim",
        "size_ligne": "18L (11.5 mm) / 24L (15.2 mm)",
        "recommended_garment": "Linen Shirts, Designer Kurtis, Casual Blazers, Bohemian Tops",
        "rate_per_gross": 290,
        "stock_gross": 480,
        "description": "ABC Buttons official SKU ABC-143. Genuine 2-hole natural river shell buttons featuring organic dark smoky and plum surface markings. Distinctive natural spotted pattern on lustrous white pearl base."
    },
    {
        "sku": "ABC-144",
        "name": "ABC-144 Pink Blush Cherry Blossom MOP Shell Button (2-Hole)",
        "category": "Shell / MOP",
        "material": "Natural Pink Lip River Shell / MOP",
        "finish": "Natural White Pearl with Organic Pink/Coral Marble Blush",
        "holes": "2-Hole with Soft Beveled Rim",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Designer Kurtis, Linen Tunics, Luxury Womenswear, Resort Wear",
        "rate_per_gross": 310,
        "stock_gross": 460,
        "description": "ABC Buttons genuine SKU ABC-144. High-grade natural river shell featuring subtle pink coral blush marbling on the back and face. 100% natural, eco-friendly luxury button."
    },
    {
        "sku": "ABC-145",
        "name": "ABC-145 Rustic Raw-Texture River Shell Button (4-Hole Chunky)",
        "category": "Shell / MOP",
        "material": "Natural Thick River Shell",
        "finish": "Organic Pitted Raw Texture with Iridescent Center Well",
        "holes": "4-Hole Center Well",
        "size_ligne": "24L (15.2 mm)",
        "recommended_garment": "Khadi Kurtas, Heavy Linen Overshirts, Safari Jackets, Organic Garment Lines",
        "rate_per_gross": 280,
        "stock_gross": 380,
        "description": "ABC Buttons genuine SKU ABC-145. Artisanal chunky shell button showcasing genuine raw shell texture, authentic natural pitting, and iridescent mother-of-pearl face."
    },
    {
        "sku": "ABC-146",
        "name": "ABC-146 Champagne Amber Pearl 4-Hole Shirt Button",
        "category": "Shell / MOP",
        "material": "Golden Lip Pearl Shell / Faux MOP",
        "finish": "Glowing Champagne Amber Luster with Raised Rim",
        "holes": "4-Hole with Raised Rim",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Executive Formal Shirts, Luxury Tuxedos, Evening Shirts, Contrast Plackets",
        "rate_per_gross": 195,
        "stock_gross": 850,
        "description": "ABC Buttons SKU ABC-146. Warm champagne amber tone with radiant mother-of-pearl shimmer. Perfect for export formal shirts and luxury designer shirting programs."
    },
    {
        "sku": "ABC-147",
        "name": "ABC-147 Classic White Chalk Pearl 4-Hole Shirt Button",
        "category": "Polyester Resin",
        "material": "High-Grade Polyester / Chalk Pearl Resin",
        "finish": "Clean Pearlized White Chalk Finish with Distinct Rim",
        "holes": "4-Hole Raised Rim",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Export Formal Shirts, Oxford Shirts, School & Corporate Uniforms, Blouses",
        "rate_per_gross": 65,
        "stock_gross": 2400,
        "description": "ABC Buttons SKU ABC-147. Industry standard 4-hole chalk pearl button. Machine washable, dry-clean safe, high impact resistance for high-speed industrial stitching."
    },
    {
        "sku": "ABC-148",
        "name": "ABC-148 Seafoam Green & Teal Swirl Shell Button (4-Hole)",
        "category": "Shell / MOP",
        "material": "Natural Trocas Shell with Seafoam Dye",
        "finish": "Vibrant Teal & Seafoam Green Iridescent Luster",
        "holes": "4-Hole Center Well",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Resort Wear, Italian Style Contrast Shirts, Summer Collections, Designer Tops",
        "rate_per_gross": 325,
        "stock_gross": 440,
        "description": "ABC Buttons SKU ABC-148. Premium 4-hole seafoam green dyed natural shell button. Retains authentic shell grain with refreshing ocean teal undertones."
    },
    {
        "sku": "ABC-149",
        "name": "ABC-149 Violet Lip Swirl MOP Shell Button (4-Hole)",
        "category": "Shell / MOP",
        "material": "Natural Violet Lip Sea Shell / MOP",
        "finish": "Pearl White with Natural Violet / Plum Swirl Marbling",
        "holes": "4-Hole Center Well",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Designer Shirts, Luxury Womenswear, High-End Festive Kurtis",
        "rate_per_gross": 320,
        "stock_gross": 550,
        "description": "ABC Buttons official SKU ABC-149. Natural sea shell button featuring unique organic purple-plum lip markings. Each piece has a one-of-a-kind natural swirl pattern."
    },
    {
        "sku": "ABC-150",
        "name": "ABC-150 Olive Moss Swirl Trocas Shell Button (4-Hole)",
        "category": "Shell / MOP",
        "material": "Natural Trocas Sea Shell with Earth Moss Pattern",
        "finish": "Organic Olive Green & Earth Swirl Marbling",
        "holes": "4-Hole Center Well",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Safari Shirts, Khadi Kurtas, Earth-Tone Linen Collections, Overshirts",
        "rate_per_gross": 295,
        "stock_gross": 420,
        "description": "ABC Buttons official SKU ABC-150. Authentic trocas shell with earthy olive moss patterns. Highly durable, natural luster, suitable for garment export washing."
    },
    {
        "sku": "ABC-151",
        "name": "ABC-151 Smoky Charcoal Black Pearl Shell Button (2-Hole)",
        "category": "Shell / MOP",
        "material": "Natural Black Lip Oyster Shell",
        "finish": "Smoky Charcoal Pearl Luster with Red Silk Oyster Presentation",
        "holes": "2-Hole Rim",
        "size_ligne": "24L (15.2 mm)",
        "recommended_garment": "Formal Tuxedos, Dark Linen Kurtas, Evening Blazers, Designer Waistcoats",
        "rate_per_gross": 340,
        "stock_gross": 390,
        "description": "ABC Buttons official SKU ABC-151. Premium Tahitian black lip pearl oyster button with deep charcoal iridescence. 2-hole rim design for high-end tailoring."
    },
    {
        "sku": "ABC-152",
        "name": "ABC-152 Natural White Sea Cowrie Shell Beads (Kaudi)",
        "category": "Shell & Craft Embellishments",
        "material": "100% Genuine Natural Sea Cowrie (Kaudi)",
        "finish": "Natural Polished Gloss with Slit for Stitching",
        "holes": "Natural Slit & Pierced Stitching Hole",
        "size_ligne": "Standard Kaudi (16 - 18 mm)",
        "recommended_garment": "Ethnic Lehengas, Dupattas, Bohemian Blouses, Banjara Jackets, Handbags & Lace Trims",
        "rate_per_gross": 260,
        "stock_gross": 1500,
        "description": "ABC Buttons SKU ABC-152. Genuine natural sea cowries (kaudi). Pre-cut back and pierced for easy manual and machine garment stitching. Very popular in bridal and boho collections."
    },
    {
        "sku": "ABC-153",
        "name": "ABC-153 Electroplated Metallic Gold Cowrie Shell Charms",
        "category": "Shell & Craft Embellishments",
        "material": "Natural Sea Cowrie Shell with 24K Gold Electroplating",
        "finish": "High-Mirror Metallic Gold Electroplated Gloss",
        "holes": "Pierced Hole for Garment Stitching / Latkans",
        "size_ligne": "Standard Kaudi (16 - 18 mm)",
        "recommended_garment": "Bridal Lehengas, Designer Cholis, Festive Latkans, Luxury Trims, Wedding Ensembles",
        "rate_per_gross": 480,
        "stock_gross": 720,
        "description": "ABC Buttons SKU ABC-153. Premium real cowrie shell with electroplated gold finish. Non-tarnish coating, ideal for luxury bridal wear, tassels, and ethnic lace embellishments."
    },
    {
        "sku": "ABC-POLY-18L-08",
        "name": "Chalk Finish Standard Polyester Shirt Button",
        "category": "Polyester Resin",
        "material": "High-Grade Polyester Resin",
        "finish": "Matte Chalk Dull Finish",
        "holes": "4-Hole Center Well",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Everyday Formal Shirts, Corporate Uniforms, Workwear",
        "rate_per_gross": 45,
        "stock_gross": 3100,
        "description": "Dye-to-match capability. Zero chipping, high impact resistance for industrial laundry."
    },
    {
        "sku": "ABC-POLY-18L-10",
        "name": "Pearlized Polyester Faux-MOP Shirt Button",
        "category": "Polyester Resin",
        "material": "Unsaturated Polyester Resin with Pearl Pigment",
        "finish": "High Gloss Pearlized Sheen",
        "holes": "4-Hole with Raised Rim",
        "size_ligne": "18L (11.5 mm)",
        "recommended_garment": "Mass-market Formal Shirts, Party Wear Shirts",
        "rate_per_gross": 55,
        "stock_gross": 2200,
        "description": "Simulates natural shell luster at an economical budget. Excellent shine and chemical resistance."
    }
]

def search_catalog_by_text(query: str):
    query = query.lower()
    results = []
    for item in SAMPLE_CATALOG:
        text = f"{item['sku']} {item['name']} {item['category']} {item['material']} {item['finish']} {item['recommended_garment']}".lower()
        if any(word in text for word in query.split()):
            results.append(item)
    return results or SAMPLE_CATALOG[:5]
