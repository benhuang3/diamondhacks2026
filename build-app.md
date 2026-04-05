# Build App Workflow — Execution Guide
I want to build an app that reviews a digital storefront with 2 functions. It should have a website and Chrome extension.

## Scan
With an agent using Browser Use, it scans the website points out accessiblity and unintuitive UIUX elements. After scanning, using HTML injection through the Chrome extension, these elements are highlighted in the webpage. Another agent also generates a report with scores and visualizations for hwo well each part of the website flows to the app website.


## Find Competitors
With a team of agents and a custom prompt (not necessary), the app scrapes the web for similar storefronts, navigates them using Browser Use, compares prices, sales, deals, discounts, tax, shipping fees, etc between other websites. The agents should attempt to check out similar products to see prices and potentially deals. This then generates a report for biggest competitors, price differences, and potential store and pricing improvements with visualizations.

# Execution Plan


### Revisions


1. The price breakdown should be by product, where it shows which products have the biggest price difference between you and your competitors.

2. After scanning, the plugin should show a sidebar of changes where you can click to each issue and view it.

3. Implement the feature so that attempts to check out and scans the pages along the way, with a maximum depth of MAX_SCAN_PAGES=10. It should do a shallow breadth first search and try to check out an item, to see shipping tax, other fees, and the final price.

4. 



