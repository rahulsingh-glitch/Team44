# Creates the hidden .claude folder from the visible claude-setup folder.
Write-Host "Installing Claude Code config into .claude ..."
New-Item -ItemType Directory -Force -Path ".claude\agents"   | Out-Null
New-Item -ItemType Directory -Force -Path ".claude\commands" | Out-Null
Copy-Item "claude-setup\agents\*"   ".claude\agents\"   -Force
Copy-Item "claude-setup\commands\*" ".claude\commands\" -Force
Write-Host "Done. Agents:"; Get-ChildItem ".claude\agents"   | Select-Object -Expand Name
Write-Host "Commands:";     Get-ChildItem ".claude\commands" | Select-Object -Expand Name
Write-Host "Now run:  claude   (from this folder), then type /"
