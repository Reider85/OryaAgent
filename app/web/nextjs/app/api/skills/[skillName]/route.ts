import { NextRequest, NextResponse } from 'next/server';
import { getSkillByName, activateSkill } from '@/lib/api/skills';

export async function GET(
  request: NextRequest,
  { params }: { params: { skillName: string } }
) {
  try {
    const skillName = params.skillName;
    const skill = await getSkillByName(skillName);
    
    if (!skill) {
      return NextResponse.json(
        { error: 'Skill not found' },
        { status: 404 }
      );
    }

    return NextResponse.json(skill);
  } catch (error) {
    console.error('Error fetching skill:', error);
    return NextResponse.json(
      { error: 'Failed to fetch skill' },
      { status: 500 }
    );
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: { skillName: string } }
) {
  try {
    const skillName = params.skillName;
    const result = await activateSkill(skillName);
    
    return NextResponse.json(result);
  } catch (error) {
    console.error('Error activating skill:', error);
    return NextResponse.json(
      { error: 'Failed to activate skill' },
      { status: 500 }
    );
  }
}