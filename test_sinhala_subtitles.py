"""
Test script to verify Sinhala subtitle rendering
Creates a test ASS file and verifies font configuration
"""
from pathlib import Path
from subtitle_processor import SubtitleProcessor
from logger import logger
import sys

def create_test_sinhala_subtitle():
    """Create a test Sinhala subtitle file"""
    temp_dir = Path('temp')
    temp_dir.mkdir(exist_ok=True)
    
    test_srt = temp_dir / 'test_sinhala.srt'
    
    # Create SRT with Sinhala text
    sinhala_content = """1
00:00:01,000 --> 00:00:05,000
සුභ උදෑසනක් වේවා

2
00:00:05,500 --> 00:00:10,000
මම සිංහල උපසිරැසි පරීක්ෂා කරනවා

3
00:00:10,500 --> 00:00:15,000
ඔබට මෙය කියවිය හැකිද?

4
00:00:15,500 --> 00:00:20,000
අපි බලමු මෙය වැඩ කරනවාද
"""
    
    test_srt.write_text(sinhala_content, encoding='utf-8')
    logger.info(f"Created test Sinhala SRT file: {test_srt}")
    return test_srt

def test_ass_conversion():
    """Test SRT to ASS conversion with Sinhala font"""
    try:
        processor = SubtitleProcessor()
        
        # Create test subtitle
        logger.info("Creating test Sinhala subtitle...")
        test_srt = create_test_sinhala_subtitle()
        
        # Convert to ASS
        logger.info("Converting SRT to ASS format...")
        ass_file = processor.ensure_ass_subtitle(test_srt)
        
        # Read and display the ASS content
        logger.info(f"ASS file created: {ass_file}")
        ass_content = ass_file.read_text(encoding='utf-8')
        
        print("\n" + "="*60)
        print("ASS FILE CONTENT:")
        print("="*60)
        print(ass_content)
        print("="*60)
        
        # Check if bindumathi font is properly set
        if 'bindumathi' in ass_content.lower():
            logger.info("✓ SUCCESS: bindumathi font is set in ASS file")
        else:
            logger.warning("⚠ WARNING: bindumathi font not found in ASS file")
        
        # Check if Sinhala text is preserved
        if 'සුභ' in ass_content or 'සිංහල' in ass_content:
            logger.info("✓ SUCCESS: Sinhala text is preserved in ASS file")
        else:
            logger.error("✗ ERROR: Sinhala text is corrupted or missing")
        
        return ass_file
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_fontconfig():
    """Test fontconfig file creation"""
    try:
        processor = SubtitleProcessor()
        
        logger.info("Creating fontconfig file...")
        fonts_conf = processor.create_fontconfig_file()
        
        if fonts_conf.exists():
            logger.info(f"✓ SUCCESS: fontconfig file created at {fonts_conf}")
            
            # Display content
            print("\n" + "="*60)
            print("FONTCONFIG FILE CONTENT:")
            print("="*60)
            print(fonts_conf.read_text(encoding='utf-8'))
            print("="*60)
            
            return True
        else:
            logger.error("✗ ERROR: fontconfig file was not created")
            return False
            
    except Exception as e:
        logger.error(f"Fontconfig test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_font_discovery():
    """Test font file discovery"""
    try:
        processor = SubtitleProcessor()
        
        logger.info("Testing font discovery...")
        font_path = processor.find_sinhala_font()
        
        font_file = Path(font_path)
        if font_file.exists():
            logger.info(f"✓ SUCCESS: Found Sinhala font at {font_path}")
            logger.info(f"  Font file size: {font_file.stat().st_size / 1024:.2f} KB")
            return True
        else:
            logger.warning(f"⚠ WARNING: Font file not found at {font_path}")
            logger.warning("  Font rendering may fail during subtitle burning")
            return False
            
    except Exception as e:
        logger.error(f"Font discovery test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("SINHALA SUBTITLE RENDERING TEST SUITE")
    print("="*60 + "\n")
    
    results = {}
    
    # Test 1: Font discovery
    print("\n[TEST 1] Font Discovery")
    print("-" * 60)
    results['font_discovery'] = test_font_discovery()
    
    # Test 2: Fontconfig creation
    print("\n[TEST 2] Fontconfig File Creation")
    print("-" * 60)
    results['fontconfig'] = test_fontconfig()
    
    # Test 3: ASS conversion
    print("\n[TEST 3] SRT to ASS Conversion with Sinhala")
    print("-" * 60)
    ass_file = test_ass_conversion()
    results['ass_conversion'] = ass_file is not None
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name.replace('_', ' ').title()}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! Sinhala subtitle rendering should work correctly.")
        print("  You can now use hard subtitle burning with Sinhala text.")
    else:
        print("\n⚠ Some tests failed. Please check the errors above.")
        print("  Sinhala subtitles may not render correctly.")
    
    print("="*60 + "\n")
    
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
