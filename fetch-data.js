// Convert Google Sheets CSV to JSON format for dashboard
async function convertGoogleSheetData() {
  const csvUrl = "https://docs.google.com/spreadsheets/d/1AxmpCZhsQ-rFAJkgYrTbPby6FEG8HHkbL60IStUl-ak/export?format=csv"; // Paste your CSV URL here
  
  const response = await fetch(csvUrl);
  const csv = await response.text();
  const lines = csv.split('\n').slice(1); // Skip header
  
  const data = lines.map(line => {
    const cols = line.split(',').map(c => c.trim());
    return [
      cols[0],  // District
      cols[1],  // Tehsil
      cols[2],  // Markaz
      cols[3],  // Wing
      cols[5],  // EMIS
      cols[6],  // School
      parseInt(cols[12]) || 0,  // Baseline
      parseInt(cols[16]) || 0,  // Current
      parseInt(cols[17]) || 0,  // Target
      parseInt(cols[21]) || 0   // Previous
    ];
  }).filter(r => r[0]); // Remove empty rows
  
  return data;
}
