# Japan Land Survey Assistant - QGIS Plugin

A comprehensive QGIS plugin for Japanese cadastral survey and land acquisition operations.

## Features

### MOJ XML Loading
- Load parcel data from Ministry of Justice (MOJ) XML files
- Automatic coordinate system detection and transformation
- Integration with MOJXML Loader plugin if available

### Kokudo Suuchi Info (National Land Numerical Information)
- Download administrative boundaries, roads, and other datasets
- Direct access to Kokudo Suuchi Info API

### Cadastral Survey Progress Visualization
- View cadastral survey progress by municipality
- Color-coded visualization based on completion rate
- Data from official cadastral survey statistics

### Parcel Search
- Search parcels by address or parcel number
- Click on map to identify parcel information
- Display parcel details including area and land category

### Land Price Overlay
- Overlay land price data from Real Estate Information Library API
- Visualize land price trends in your area

### Plugin Integration
- Automatic detection of related plugins (MOJXML Loader, jpdata, QuickDEM4JP)
- Seamless integration when available

## Installation

### From QGIS Plugin Repository
1. Open QGIS
2. Go to `Plugins` > `Manage and Install Plugins...`
3. Search for "Japan Land Survey Assistant"
4. Click `Install`

### From ZIP file
1. Download the plugin ZIP file from [Releases](https://github.com/akitaneko1127/japan_land_survey_assistant/releases)
2. Open QGIS
3. Go to `Plugins` > `Manage and Install Plugins...`
4. Select `Install from ZIP`
5. Browse to the downloaded ZIP file and install

## Usage

1. Click the "地籍調査支援" button in the toolbar or go to `Vector` > `Japan Land Survey Assistant`
2. Use the tabbed interface to access different features:
   - **Data Loader**: Load MOJ XML or Kokudo Suuchi Info data
   - **Parcel Search**: Search and identify parcels
   - **Progress Viewer**: View cadastral survey progress
   - **Land Price**: Overlay land price information

## Processing Algorithms

This plugin provides the following processing algorithms:

- **Load MOJ XML**: Load parcel data from MOJ XML files
- **Load Kokudo Suuchi Info**: Download national land numerical information
- **Visualize Progress**: Create cadastral progress visualization
- **Search Parcel**: Search parcels by address or number

## Requirements

- QGIS 3.28 or later
- Internet connection for API features

## Optional Dependencies

- MOJXML Loader plugin (for enhanced MOJ XML support)
- jpdata plugin (for Japanese address data)
- QuickDEM4JP plugin (for elevation data)

## License

This plugin is licensed under the GNU General Public License v2 (GPLv2).

## Author

link-field

## Support

- GitHub: https://github.com/akitaneko1127/japan_land_survey_assistant
- Issues: https://github.com/akitaneko1127/japan_land_survey_assistant/issues
