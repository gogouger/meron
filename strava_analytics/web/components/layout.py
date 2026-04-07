"""Reusable layout primitives — matches ozniai.com page structure."""

from dash import html, dcc

from strava_analytics.web.theme import ACCENT


def hero_section(label, headline, subtext, cta_buttons=None):
    """Full-width hero matching ozniai.com hero pattern."""
    children = [
        html.Span(label, className="hero-label scramble-label"),
        html.H1(headline, className="hero-headline"),
        html.P(subtext, className="hero-subtext"),
    ]
    if cta_buttons:
        children.append(html.Div(cta_buttons, className="hero-buttons"))

    return html.Div(
        html.Div(children, className="hero-inner"),
        className="hero-section",
    )


def page_section(label, children, alt_bg=False, border_top=True):
    """Content section with border separator and optional alt background."""
    classes = ["page-section"]
    if alt_bg:
        classes.append("page-section--alt")
    if border_top:
        classes.append("page-section--border")

    inner_children = []
    if label:
        inner_children.append(
            html.Span(label, className="section-label scramble-label")
        )
    if isinstance(children, list):
        inner_children.extend(children)
    else:
        inner_children.append(children)

    return html.Div(
        html.Div(inner_children, className="section-inner"),
        className=" ".join(classes),
    )


def statement_section(label, text):
    """Large bold statement — ozniai.com 'OUR MISSION' pattern."""
    return html.Div(
        html.Div([
            html.Span(label, className="statement-label scramble-label"),
            html.P(text, className="statement-text"),
        ], className="statement-inner"),
        className="statement-section",
    )


def feature_grid(children, columns=3):
    """Responsive CSS grid matching ozniai.com card layouts."""
    cls = "feature-grid"
    if columns == 4:
        cls = "feature-grid feature-grid--4"
    elif columns == 2:
        cls = "feature-grid feature-grid--2"
    return html.Div(children, className=cls)


def numbered_card(number, title, description="", value=None, subtitle="",
                  color=ACCENT, link_text=None, link_href=None, children=None):
    """ozniai.com '01 / Edge Intelligence' capability card."""
    card_children = [
        html.Div(f"{number:02d}", className="numbered-card__number"),
        html.Div(title, className="numbered-card__title"),
    ]
    if value is not None:
        card_children.append(
            html.Div(str(value), className="numbered-card__value",
                     style={"color": color})
        )
    if subtitle:
        card_children.append(
            html.P(subtitle, className="numbered-card__subtitle")
        )
    if description:
        card_children.append(
            html.P(description, className="numbered-card__desc")
        )
    if children:
        if isinstance(children, list):
            card_children.extend(children)
        else:
            card_children.append(children)
    if link_text and link_href:
        card_children.append(
            dcc.Link([
                link_text,
                html.Span(" \u2192"),
            ], href=link_href, className="numbered-card__link")
        )

    return html.Div(card_children, className="numbered-card")


def product_card(title, children):
    """Clean card with accent top-border for race predictions etc."""
    inner = [html.Div(title, className="product-card__name")]
    if isinstance(children, list):
        inner.extend(children)
    else:
        inner.append(children)
    return html.Div(inner, className="product-card")


def cta_section(headline, subtext=None, link_text=None, link_href=None):
    """Centered CTA band matching ozniai.com pattern."""
    children = [html.H2(headline, className="cta-headline")]
    if subtext:
        children.append(html.P(subtext, className="cta-subtext"))
    if link_text and link_href:
        children.append(
            dcc.Link(link_text, href=link_href, className="btn-accent")
        )
    return html.Div(
        html.Div(children, className="cta-inner"),
        className="cta-section",
    )


def footer():
    """3-column footer matching ozniai.com."""
    return html.Footer(
        html.Div([
            html.Div([
                # Column 1: Brand
                html.Div([
                    html.Div("Strava Analytics", className="footer-brand"),
                    html.P("Personal fitness intelligence, built from your data.",
                           className="footer-tagline"),
                    html.P("Denver, CO",
                           className="footer-tagline",
                           style={"marginTop": "8px"}),
                ]),
                # Column 2: Navigation
                html.Div([
                    html.Div("Navigation", className="footer-heading"),
                    dcc.Link("Overview", href="/", className="footer-link"),
                    dcc.Link("Running", href="/running", className="footer-link"),
                    dcc.Link("Lifting", href="/lifting", className="footer-link"),
                    dcc.Link("Predictions", href="/races", className="footer-link"),
                    dcc.Link("Plan", href="/plan", className="footer-link"),
                ]),
                # Column 3: Built with
                html.Div([
                    html.Div("Built With", className="footer-heading"),
                    html.P("Questionable life choices, too much Strava data, "
                           "and a mass amount of coffee.",
                           className="footer-tagline"),
                ]),
            ], className="footer-grid"),
            html.Div("\u00a9 2026 Strava Analytics. All rights reserved.",
                     className="footer-copyright"),
        ], className="footer-inner"),
        className="site-footer",
    )
