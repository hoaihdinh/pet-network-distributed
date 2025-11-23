# fix-and-restart.ps1
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Fixing Database Initialization Issue" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`nStep 1: Stopping all services..." -ForegroundColor Yellow
docker-compose -f docker-compose-layered.yml down -v

Write-Host "`nStep 2: Starting databases first..." -ForegroundColor Yellow
docker-compose -f docker-compose-layered.yml up -d postgres-layered redis-layered

Write-Host "`nStep 3: Waiting 30 seconds for databases..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

Write-Host "`nStep 4: Checking PostgreSQL readiness..." -ForegroundColor Yellow
$pgReady = docker exec postgres-layered pg_isready -U petuser
Write-Host $pgReady

Write-Host "`nStep 5: Starting application services..." -ForegroundColor Yellow
docker-compose -f docker-compose-layered.yml up --build --no-cache -d

Write-Host "`nStep 6: Waiting 45 seconds for initialization..." -ForegroundColor Yellow
Start-Sleep -Seconds 45

Write-Host "`nStep 7: Checking service status..." -ForegroundColor Yellow
docker-compose -f docker-compose-layered.yml ps

Write-Host "`nStep 8: Verifying database schema..." -ForegroundColor Yellow
docker exec postgres-layered psql -U petuser -d pet_reports -c "\dt"

Write-Host "`nStep 9: Checking data-access logs..." -ForegroundColor Yellow
docker logs data-access --tail 10

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Fix Complete! Testing..." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`nTesting health endpoint..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8080/health" -Method Get
    Write-Host "✅ Health check passed: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "❌ Health check failed" -ForegroundColor Red
}

Write-Host "`nTesting report creation..." -ForegroundColor Yellow
try {
    $report = @{
        type = "lost"
        pet_type = "dog"
        breed = "test"
        color = "brown"
        location = @{
            latitude = 40.7128
            longitude = -74.0060
            address = "NYC"
        }
        description = "Test"
        contact_info = "test@example.com"
    } | ConvertTo-Json
    
    $response = Invoke-RestMethod -Uri "http://localhost:8080/api/reports" -Method Post -ContentType "application/json" -Body $report
    Write-Host "✅ Report created: $($response.id)" -ForegroundColor Green
} catch {
    Write-Host "❌ Report creation failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "`nChecking logs again..." -ForegroundColor Yellow
    docker logs data-access --tail 5
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Done!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan