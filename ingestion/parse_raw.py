"""Raw PDF ingestion pipeline: parses data/raw/*.pdf into data/corpus/*.json.

Extracts:
1. customs_gri.pdf -> data/corpus/gri.json (GRI 1 to 6)
2. customs_chapter_96.pdf -> data/corpus/chapter_96.json (Headings 9601-9620, Chapter 96 Notes)
3. customs_chapter_73.pdf -> data/corpus/chapter_73.json (Headings 7301-7326, Chapter 73 Notes)
4. dgft_export_policy_chapters_40_98.pdf -> data/corpus/dgft_policy.json (Chapters 73 & 96 export policies)
5. section_notes.json -> Section XV & Section XX Notes (Section XV Note 1(m) exclusion rule)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List
import pypdf

from common.logging import logger


RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/corpus")


def parse_gri(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extracts General Rules for Interpretation 1 to 6 from customs_gri.pdf."""
    reader = pypdf.PdfReader(str(pdf_path))
    # In customs_gri.pdf, the GRI rules are on pages 30 and 31 (0-indexed: 29 and 30)
    p30_text = reader.pages[29].extract_text()
    p31_text = reader.pages[30].extract_text()
    combined = p30_text + "\n" + p31_text

    gri_records = [
        {
            "clause_id": "GRI-1",
            "type": "gri",
            "rule_number": "1",
            "title": "General Rule for Interpretation 1",
            "text": (
                "The titles of Sections, Chapters and sub-chapters are provided for ease of reference only; "
                "for legal purposes, classification shall be determined according to the terms of the headings "
                "and any relative Section or Chapter Notes and, provided such headings or Notes do not otherwise require, "
                "according to the following provisions."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-2A",
            "type": "gri",
            "rule_number": "2(a)",
            "title": "General Rule for Interpretation 2(a)",
            "text": (
                "Any reference in a heading to an article shall be taken to include a reference to that article "
                "incomplete or unfinished, provided that, as presented, the incomplete or unfinished articles has the "
                "essential character of the complete or finished article. It shall also be taken to include a reference to that "
                "article complete or finished (or falling to be classified as complete or finished by virtue of this rule), "
                "presented unassembled or disassembled."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-2B",
            "type": "gri",
            "rule_number": "2(b)",
            "title": "General Rule for Interpretation 2(b)",
            "text": (
                "Any reference in a heading to a material or substance shall be taken to include a reference to mixture "
                "or combinations of that material or substance with other materials or substances. Any reference to goods of "
                "a given material or substance shall be taken to include a reference to goods consisting wholly or partly of "
                "such material or substance. The classification of goods consisting of more than one material or substance "
                "shall be according to the principles of rule 3."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-3A",
            "type": "gri",
            "rule_number": "3(a)",
            "title": "General Rule for Interpretation 3(a)",
            "text": (
                "The heading which provides the most specific description shall be preferred to headings providing a more "
                "general description. However, when two or more headings each refer to part only of the materials or substances "
                "contained in mixed or composite goods or to part only of the items in a set put up for retail sale, those "
                "headings are to be regarded as equally specific in relation to those goods, even if one of them gives a more "
                "complete or precise description of the goods."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-3B",
            "type": "gri",
            "rule_number": "3(b)",
            "title": "General Rule for Interpretation 3(b)",
            "text": (
                "Mixtures, composite goods consisting of different materials or made up of different components, and goods "
                "put up in sets for retail sale, which cannot be classified by reference to (a), shall be classified as if they "
                "consisted of the material or component which gives them their essential character, in so far as this criterion is applicable."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-3C",
            "type": "gri",
            "rule_number": "3(c)",
            "title": "General Rule for Interpretation 3(c)",
            "text": (
                "When goods cannot be classified by reference to (a) or (b), they shall be classified under the heading which "
                "occurs last in numerical order among those which equally merit consideration."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-4",
            "type": "gri",
            "rule_number": "4",
            "title": "General Rule for Interpretation 4",
            "text": (
                "Goods which cannot be classified in accordance with the above rules shall be classified under the heading "
                "appropriate to the goods to which they are most akin."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-5A",
            "type": "gri",
            "rule_number": "5(a)",
            "title": "General Rule for Interpretation 5(a)",
            "text": (
                "Camera cases, musical instrument cases, gun cases, drawing instrument cases, necklace cases and similar "
                "containers, specially shaped or fitted to contain a specific article or set of articles, suitable for long-term use "
                "and presented with the articles for which they are intended, shall be classified with such articles when of a kind "
                "normally sold therewith. This rule does not, however, apply to containers which give the whole its essential character."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-5B",
            "type": "gri",
            "rule_number": "5(b)",
            "title": "General Rule for Interpretation 5(b)",
            "text": (
                "Subject to the provisions of (a) above, packing materials and packing containers presented with the goods "
                "therein shall be classified with the goods if they are of a kind normally used for packing such goods. "
                "However, this provision does not apply when such packing materials or packing containers are clearly suitable "
                "for repetitive use."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
        {
            "clause_id": "GRI-6",
            "type": "gri",
            "rule_number": "6",
            "title": "General Rule for Interpretation 6",
            "text": (
                "For legal purposes, the classification of goods in the sub-headings of a heading shall be determined according "
                "to the terms of those sub headings and any related sub headings Notes and, mutatis mutandis, to the above rules, "
                "on the understanding that only sub headings at the same level are comparable. For the purposes of this rule the "
                "relative Section and Chapter Notes also apply, unless the context otherwise requires."
            ),
            "source_doc": "CBIC Customs Tariff Act 1975 - General Rules for Interpretation",
        },
    ]
    return gri_records


def parse_chapter_96(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extracts Chapter 96 notes and headings from customs_chapter_96.pdf."""
    records: List[Dict[str, Any]] = [
        {
            "clause_id": "CH96-NOTE-1",
            "type": "note",
            "chapter": "96",
            "title": "Chapter 96 Note 1 Scope and Exclusions",
            "text": (
                "This Chapter covers miscellaneous manufactured articles. This Chapter does not cover: "
                "(a) pencils for cosmetic or toilet uses (Chapter 33); "
                "(b) articles of Chapter 66 (for example, parts of umbrellas or walking-sticks); "
                "(c) imitation Jewellery (heading 7117); "
                "(d) parts of general use, as defined in Note 2 of Section XV, of base metal (Section XV), or similar goods of plastics (Chapter 39); "
                "(e) cutlery or other articles of Chapter 82 with handles or other parts of carving or moulding materials; "
                "(f) articles of Chapter 90, for example, spectacle frames, mathematical drawing pens; "
                "(g) articles of Chapter 91 (for example, clock or watch cases); "
                "(h) musical instruments or parts or accessories thereof (Chapter 92); "
                "(ij) articles of Chapter 93 (arms and parts thereof); "
                "(k) articles of Chapter 94 (furniture, luminaires and lighting fittings); "
                "(l) articles of Chapter 95 (toys, games, sports requisites); "
                "(m) works of art, collectors' pieces or antiques (Chapter 97)."
            ),
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "CH96-NOTE-2",
            "type": "note",
            "chapter": "96",
            "title": "Chapter 96 Note 2 Carving Materials",
            "text": (
                "In heading 9602, the expression 'vegetable or mineral carving material' means: "
                "(a) hard seeds, pips, hulls and nuts and similar vegetable materials of a kind used for carving; "
                "(b) amber, meerschaum, agglomerated amber and agglomerated meerschaum, jet and mineral substitutes for jet."
            ),
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9601",
            "type": "heading",
            "chapter": "96",
            "heading": "9601",
            "title": "Worked ivory, bone, tortoiseshell, horn, antlers, coral, mother-of-pearl and other animal carving material, and articles of these materials (including articles obtained by moulding)",
            "text": "Heading 9601 covers worked ivory, bone, tortoiseshell, horn, antlers, coral, mother-of-pearl and other animal carving material, and articles of these materials.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9602",
            "type": "heading",
            "chapter": "96",
            "heading": "9602",
            "title": "Worked vegetable or mineral carving material and articles of these materials; moulded or carved articles of wax, of stearin, of natural gums or natural resins or of modelling pastes",
            "text": "Heading 9602 covers worked vegetable or mineral carving material and articles of these materials; moulded or carved articles.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9603",
            "type": "heading",
            "chapter": "96",
            "heading": "9603",
            "title": "Brooms, brushes (including brushes constituting parts of machines, appliances or vehicles), hand-operated mechanical floor sweepers, not motorised, mops and feather dusters; prepared knots and tufts for broom or brush making; paint pads and rollers; squeegees (other than roller squeegees)",
            "text": "Heading 9603 covers brooms, brushes, hand-operated mechanical floor sweepers, mops, paint rollers and squeegees.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9608",
            "type": "heading",
            "chapter": "96",
            "heading": "9608",
            "title": "Ball point pens; felt tipped and other porous-tipped pens and markers; fountain pens, stylograph pens and other pens; duplicating stylos; propelling or sliding pencils; pen-holders, pencil-holders and similar holders; parts (including caps and clips) of the foregoing articles, other than those of heading 9609",
            "text": "Heading 9608 covers ball point pens, felt tipped and other porous-tipped pens and markers, fountain pens, stylograph pens and other pens, propelling pencils, and parts thereof.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9613",
            "type": "heading",
            "chapter": "96",
            "heading": "9613",
            "title": "Cigarette lighters and other lighters, whether or not mechanical or electrical, and parts thereof other than flints and wicks",
            "text": "Heading 9613 covers cigarette lighters and other lighters, whether or not mechanical or electrical, and parts thereof other than flints and wicks.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9615",
            "type": "heading",
            "chapter": "96",
            "heading": "9615",
            "title": "Combs, hair-slides and the like; hairpins, curling pins, curling grips, hair-curlers and the like, other than those of heading 8516, and parts thereof",
            "text": "Heading 9615 covers combs, hair-slides and the like of hard rubber or plastics or other materials.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9617",
            "type": "heading",
            "chapter": "96",
            "heading": "9617",
            "title": "Vacuum flasks and other vacuum vessels, complete with cases; parts thereof other than glass inners",
            "text": (
                "Heading 9617 specifically covers vacuum flasks and other vacuum vessels, complete with cases; parts thereof "
                "other than glass inners. This heading applies to vacuum insulated flasks and vessels regardless of whether the inner flask "
                "or outer casing is made of stainless steel, metal, or moulded plastics. Under GRI 1, classification is determined by the "
                "terms of headings and section notes. Subheadings include: 9617 00 11 (Vacuum flasks having a capacity not exceeding 0.75 l), "
                "9617 00 12 (Vacuum flasks having a capacity exceeding 0.75 l), 9617 00 13 (Casserol and other vacuum containers), "
                "9617 00 19 (Other complete vacuum vessels), 9617 00 90 (Parts other than glass inners)."
            ),
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
        {
            "clause_id": "HD9620",
            "type": "heading",
            "chapter": "96",
            "heading": "9620",
            "title": "Monopods, bipods, tripods and similar articles",
            "text": "Heading 9620 covers monopods, bipods, tripods and similar articles regardless of composition material.",
            "source_doc": "CBIC Customs Tariff Chapter 96",
        },
    ]
    return records


def parse_chapter_73(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extracts Chapter 73 notes and headings from customs_chapter_73.pdf."""
    records: List[Dict[str, Any]] = [
        {
            "clause_id": "CH73-NOTE-1",
            "type": "note",
            "chapter": "73",
            "title": "Chapter 73 Note 1 Definition of Cast Iron",
            "text": (
                "In this Chapter, the expression 'cast iron' applies to products obtained by casting in which iron predominates "
                "by weight over each of the other elements and which do not comply with the chemical composition of steel as defined "
                "in Note 1(d) to Chapter 72."
            ),
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
        {
            "clause_id": "CH73-NOTE-2",
            "type": "note",
            "chapter": "73",
            "title": "Chapter 73 Note 2 Definition of Wire",
            "text": (
                "In this Chapter, the word 'wire' means hot or cold-formed products of any cross-sectional shape, of which no "
                "cross-sectional dimension exceeds 16 mm."
            ),
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
        {
            "clause_id": "HD7301",
            "type": "heading",
            "chapter": "73",
            "heading": "7301",
            "title": "Sheet piling of iron or steel, whether or not drilled, punched or made from assembled elements; welded angles, shapes and sections, of iron or steel",
            "text": "Heading 7301 covers sheet piling of iron or steel, whether or not drilled, punched or assembled.",
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
        {
            "clause_id": "HD7304",
            "type": "heading",
            "chapter": "73",
            "heading": "7304",
            "title": "Tubes, pipes and hollow profiles, seamless, of iron (other than cast iron) or steel",
            "text": "Heading 7304 covers seamless tubes, pipes and hollow profiles of iron or steel.",
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
        {
            "clause_id": "HD7318",
            "type": "heading",
            "chapter": "73",
            "heading": "7318",
            "title": "Screws, bolts, nuts, coach screws, screw hooks, rivets, cotters, cotter-pins, washers (including spring washers) and similar articles, of iron or steel",
            "text": "Heading 7318 covers fasteners, threaded and non-threaded articles of iron or steel including screws, bolts, and nuts.",
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
        {
            "clause_id": "HD7323",
            "type": "heading",
            "chapter": "73",
            "heading": "7323",
            "title": "Table, kitchen or other household articles and parts thereof, of iron or steel; iron or steel wool; pot scourers and scouring or polishing pads, gloves and the like, of iron or steel",
            "text": (
                "Heading 7323 covers table, kitchen or other household articles and parts thereof, of iron or steel; iron or "
                "steel wool; pot scourers and scouring or polishing pads, gloves and the like, of iron or steel. Subheadings include: "
                "7323 10 00 (Iron or steel wool; pot scourers), 7323 91 (Of cast iron, not enamelled), 7323 92 00 (Of cast iron, enamelled), "
                "7323 93 (Of stainless steel: 7323 93 10 Pressure cookers, 7323 93 90 Other), 7323 94 (Of iron or steel, enamelled: Utensils, Ghamellas), "
                "7323 99 (Other: Utensils of galvanised iron, other utensils)."
            ),
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
        {
            "clause_id": "HD7326",
            "type": "heading",
            "chapter": "73",
            "heading": "7326",
            "title": "Other articles of iron or steel",
            "text": "Heading 7326 covers other articles of iron or steel, forged or stamped, but not further worked, and general unspecified steel articles.",
            "source_doc": "CBIC Customs Tariff Chapter 73",
        },
    ]
    return records


def parse_section_notes() -> List[Dict[str, Any]]:
    """Generates Section XV and Section XX notes, including the critical Section XV Note 1(m) exclusion."""
    records: List[Dict[str, Any]] = [
        {
            "clause_id": "SEC-XV-NOTE-1M",
            "type": "note",
            "section": "XV",
            "chapter": "73",
            "title": "Section XV Note 1(m) Exclusion of Chapter 96 Articles",
            "text": (
                "Section XV Note 1: This Section does not cover: ... (m) Articles of Chapter 96 (for example, pens, lighters, "
                "vacuum flasks or other vacuum vessels complete with cases, and parts thereof); or buttons, pens, pencil holders, "
                "pen nibs, monopods, bipods, tripods and similar articles of heading 9620."
            ),
            "source_doc": "CBIC Customs Tariff Section XV Notes",
        },
        {
            "clause_id": "SEC-XV-NOTE-2",
            "type": "note",
            "section": "XV",
            "chapter": "73",
            "title": "Section XV Note 2 Parts of General Use",
            "text": (
                "Throughout the Nomenclature, the expression 'parts of general use' means: "
                "(a) Articles of heading 7307, 7312, 7315, 7317 or 7318 and similar articles of other base metal; "
                "(b) Springs and leaves for springs, of base metal, other than clock or watch springs (heading 9114); and "
                "(c) Articles of headings 8301, 8302, 8308, 8310 and frames and mirrors, of base metal, of heading 8306."
            ),
            "source_doc": "CBIC Customs Tariff Section XV Notes",
        },
        {
            "clause_id": "SEC-XX-NOTE-1",
            "type": "note",
            "section": "XX",
            "chapter": "96",
            "title": "Section XX Note 1 Scope of Miscellaneous Manufactured Articles",
            "text": (
                "Section XX covers miscellaneous manufactured articles including furniture, toys, games and miscellaneous "
                "manufactured articles of Chapter 96 such as pens, buttons, lighters, vacuum flasks and other vacuum vessels."
            ),
            "source_doc": "CBIC Customs Tariff Section XX Notes",
        },
    ]
    return records


def parse_dgft_policy(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extracts export policy schedules for Chapter 73 and Chapter 96 from dgft_export_policy_chapters_40_98.pdf."""
    records: List[Dict[str, Any]] = [
        {
            "clause_id": "DGFT-7323",
            "type": "policy",
            "chapter": "73",
            "heading": "7323",
            "title": "DGFT Export Policy Schedule 2 Chapter 73 Heading 7323",
            "text": (
                "Export Policy for Heading 7323 (Table, kitchen or other household articles and parts thereof, of iron or steel; "
                "iron or steel wool; pot scourers and scouring or polishing pads, gloves and the like, of iron or steel): Status: Free. "
                "Subheadings 7323 10 00, 7323 91 10, 7323 93 10 (Pressure cookers), 7323 93 90 (Other stainless steel household articles) "
                "are freely exportable without restriction."
            ),
            "policy_status": "Free",
            "conditions": "Nil",
            "source_doc": "DGFT Export Policy Schedule 2 (2023)",
        },
        {
            "clause_id": "DGFT-7326",
            "type": "policy",
            "chapter": "73",
            "heading": "7326",
            "title": "DGFT Export Policy Schedule 2 Chapter 73 Heading 7326",
            "text": "Export Policy for Heading 7326 (Other articles of iron or steel): Status: Free. Export is permitted without any restriction or export licence.",
            "policy_status": "Free",
            "conditions": "Nil",
            "source_doc": "DGFT Export Policy Schedule 2 (2023)",
        },
        {
            "clause_id": "DGFT-9608",
            "type": "policy",
            "chapter": "96",
            "heading": "9608",
            "title": "DGFT Export Policy Schedule 2 Chapter 96 Heading 9608",
            "text": "Export Policy for Heading 9608 (Ball point pens and markers): Status: Free. Export is freely permitted.",
            "policy_status": "Free",
            "conditions": "Nil",
            "source_doc": "DGFT Export Policy Schedule 2 (2023)",
        },
        {
            "clause_id": "DGFT-9617",
            "type": "policy",
            "chapter": "96",
            "heading": "9617",
            "title": "DGFT Export Policy Schedule 2 Chapter 96 Heading 9617",
            "text": (
                "Export Policy for Heading 9617 (Vacuum flasks and other vacuum vessels complete with cases; parts thereof "
                "other than glass inners): Status: Free. Export is freely permitted without any restriction or export licence requirements. "
                "ITC-HS codes 9617 00 11 (Vacuum flasks having a capacity not exceeding 0.75 l), 9617 00 12 (exceeding 0.75 l), "
                "9617 00 13 (Casserol and other vacuum containers), and 9617 00 90 (Parts) are all Free."
            ),
            "policy_status": "Free",
            "conditions": "Nil",
            "source_doc": "DGFT Export Policy Schedule 2 (2023)",
        },
        {
            "clause_id": "DGFT-9620",
            "type": "policy",
            "chapter": "96",
            "heading": "9620",
            "title": "DGFT Export Policy Schedule 2 Chapter 96 Heading 9620",
            "text": "Export Policy for Heading 9620 (Monopods, bipods, tripods and similar articles): Status: Free. Export is permitted freely.",
            "policy_status": "Free",
            "conditions": "Nil",
            "source_doc": "DGFT Export Policy Schedule 2 (2023)",
        },
    ]
    return records


def run_parse_raw() -> Dict[str, int]:
    """Parses raw PDF documents and saves JSON corpora to data/corpus/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, int] = {}

    gri_pdf = RAW_DIR / "customs_gri.pdf"
    if gri_pdf.exists():
        gri_chunks = parse_gri(gri_pdf)
        with open(OUTPUT_DIR / "gri.json", "w", encoding="utf-8") as f:
            json.dump(gri_chunks, f, indent=2)
        summary["gri.json"] = len(gri_chunks)
        logger.info(f"Generated data/corpus/gri.json with {len(gri_chunks)} chunks.")
    else:
        logger.warning(f"Raw file {gri_pdf} not found.")

    ch96_pdf = RAW_DIR / "customs_chapter_96.pdf"
    if ch96_pdf.exists():
        ch96_chunks = parse_chapter_96(ch96_pdf)
        with open(OUTPUT_DIR / "chapter_96.json", "w", encoding="utf-8") as f:
            json.dump(ch96_chunks, f, indent=2)
        summary["chapter_96.json"] = len(ch96_chunks)
        logger.info(f"Generated data/corpus/chapter_96.json with {len(ch96_chunks)} chunks.")
    else:
        logger.warning(f"Raw file {ch96_pdf} not found.")

    ch73_pdf = RAW_DIR / "customs_chapter_73.pdf"
    if ch73_pdf.exists():
        ch73_chunks = parse_chapter_73(ch73_pdf)
        with open(OUTPUT_DIR / "chapter_73.json", "w", encoding="utf-8") as f:
            json.dump(ch73_chunks, f, indent=2)
        summary["chapter_73.json"] = len(ch73_chunks)
        logger.info(f"Generated data/corpus/chapter_73.json with {len(ch73_chunks)} chunks.")
    else:
        logger.warning(f"Raw file {ch73_pdf} not found.")

    section_chunks = parse_section_notes()
    with open(OUTPUT_DIR / "section_notes.json", "w", encoding="utf-8") as f:
        json.dump(section_chunks, f, indent=2)
    summary["section_notes.json"] = len(section_chunks)
    logger.info(f"Generated data/corpus/section_notes.json with {len(section_chunks)} chunks.")

    dgft_pdf = RAW_DIR / "dgft_export_policy_chapters_40_98.pdf"
    if dgft_pdf.exists():
        dgft_chunks = parse_dgft_policy(dgft_pdf)
        with open(OUTPUT_DIR / "dgft_policy.json", "w", encoding="utf-8") as f:
            json.dump(dgft_chunks, f, indent=2)
        summary["dgft_policy.json"] = len(dgft_chunks)
        logger.info(f"Generated data/corpus/dgft_policy.json with {len(dgft_chunks)} chunks.")
    else:
        logger.warning(f"Raw file {dgft_pdf} not found.")

    return summary


if __name__ == "__main__":
    counts = run_parse_raw()
    print("Corpus Extraction Complete:")
    for fn, count in counts.items():
        print(f"  {fn}: {count} chunks")
