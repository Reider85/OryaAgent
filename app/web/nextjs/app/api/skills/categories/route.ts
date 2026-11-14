import { NextResponse } from 'next/server';

export async function GET() {
  try {
    // Mock categories - in real implementation, this would come from the backend
    const categories = [
      'Development',
      'Code Review', 
      'Testing',
      'DevOps',
      'Documentation',
      'Security',
      'Performance',
      'Architecture'
    ];

    return NextResponse.json(categories);
  } catch (error) {
    console.error('Error fetching categories:', error);
    return NextResponse.json(
      { error: 'Failed to fetch categories' },
      { status: 500 }
    );
  }
}